# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import time
import urllib.parse
import urllib.request
from google import genai
from google.cloud import firestore, storage
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from .a2ui_utils import a2ui_callback

# Hardcoded project ID string & bucket name for Firestore & Cloud Storage
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-02-57f30fd7c82f"
PUBLIC_IMAGE_BUCKET = "smart-pantry-chef-media-57f30fd7"
MEMORY_BANK_ID = "6677780517204525056"

THEMEALDB_API_KEY = os.getenv("THEMEALDB_API_KEY", "1")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# Load Agent Engine resource name from deployment_metadata.json if available
AGENT_ENGINE_RESOURCE_NAME = None
_metadata_path = os.path.join(os.path.dirname(__file__), "..", "deployment_metadata.json")
if os.path.exists(_metadata_path):
    try:
        with open(_metadata_path, "r") as f:
            _meta = json.load(f)
            AGENT_ENGINE_RESOURCE_NAME = _meta.get("remote_agent_runtime_id")
    except Exception as e:
        print(f"Warning: unable to read deployment_metadata.json: {e}")

code_executor = (
    AgentEngineSandboxCodeExecutor(agent_engine_resource_name=AGENT_ENGINE_RESOURCE_NAME)
    if AGENT_ENGINE_RESOURCE_NAME
    else None
)

RECIPE_CATALOG = [
    {
        "id": "garlic_parmesan_pasta",
        "title": "Garlic Parmesan Spaghetti",
        "description": "Simple and delicious pasta tossed with fresh garlic, olive oil, and aged parmesan.",
        "ingredients": ["pasta", "garlic", "olive_oil", "parmesan"],
        "prep_time": "15 mins",
    },
    {
        "id": "classic_scrambled_eggs",
        "title": "Classic Herb Scrambled Eggs",
        "description": "Fluffy scrambled eggs cooked in olive oil with parmesan cheese.",
        "ingredients": ["eggs", "olive_oil", "parmesan"],
        "prep_time": "10 mins",
    },
    {
        "id": "fresh_tomato_pasta",
        "title": "Fresh Tomato & Garlic Spaghetti",
        "description": "Spaghetti tossed with sautéed Roma tomatoes, garlic, olive oil, and parmesan.",
        "ingredients": ["pasta", "tomatoes", "garlic", "olive_oil", "parmesan"],
        "prep_time": "20 mins",
    },
    {
        "id": "chicken_parmigiana",
        "title": "Crispy Chicken Parmigiana",
        "description": "Breaded chicken breast topped with tomato sauce and melted parmesan.",
        "ingredients": ["chicken", "tomatoes", "parmesan", "breadcrumbs"],
        "prep_time": "35 mins",
    },
]


def _get_firestore_client():
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def list_pantry_items() -> str:
    """Lists all current items stored in the pantry inventory.

    Returns:
        A JSON formatted string of current pantry items.
    """
    try:
        db = _get_firestore_client()
        docs = db.collection("pantry_items").stream()
        items = [doc.to_dict() for doc in docs]
        if not items:
            return json.dumps({"status": "empty", "message": "No items found in pantry."})
        return json.dumps({"status": "success", "pantry_items": items}, indent=2)
    except Exception as e:
        return f"Error retrieving pantry items: {str(e)}"


def add_or_update_pantry_item(
    item_id: str,
    name: str,
    quantity: float,
    unit: str,
    category: str,
    expiration_date: str = "",
) -> str:
    """Adds a new item or updates an existing item in the pantry inventory.

    Args:
        item_id: Unique identifier for the item (e.g., 'milk', 'eggs', 'olive_oil').
        name: Display name of the item (e.g., 'Whole Milk').
        quantity: Numerical quantity available.
        unit: Unit of measurement (e.g., 'carton', 'count', 'lbs').
        category: Food category (e.g., 'Dairy', 'Produce', 'Pantry').
        expiration_date: Optional expiration date in YYYY-MM-DD format.

    Returns:
        A success message indicating the item was updated.
    """
    try:
        db = _get_firestore_client()
        item_data = {
            "item_id": item_id.lower().replace(" ", "_"),
            "name": name,
            "quantity": float(quantity),
            "unit": unit,
            "category": category,
            "expiration_date": expiration_date,
        }
        db.collection("pantry_items").document(item_data["item_id"]).set(item_data)
        return f"Successfully saved '{name}' ({quantity} {unit}) to pantry."
    except Exception as e:
        return f"Error updating pantry item: {str(e)}"


def remove_pantry_item(item_id: str) -> str:
    """Removes an item from the pantry inventory by its item ID.

    Args:
        item_id: The ID of the item to remove (e.g., 'eggs', 'tomatoes').

    Returns:
        A confirmation message.
    """
    try:
        db = _get_firestore_client()
        clean_id = item_id.lower().replace(" ", "_")
        db.collection("pantry_items").document(clean_id).delete()
        return f"Successfully removed '{clean_id}' from pantry."
    except Exception as e:
        return f"Error removing pantry item: {str(e)}"


def search_recipes_by_pantry() -> str:
    """Searches local recipe database against current pantry inventory in Firestore.

    Returns:
        A JSON string containing matching recipes and ingredient coverage.
    """
    try:
        db = _get_firestore_client()
        docs = db.collection("pantry_items").stream()
        pantry_ids = {doc.to_dict().get("item_id", "").lower() for doc in docs}

        matches = []
        for recipe in RECIPE_CATALOG:
            required = set(recipe["ingredients"])
            missing = required - pantry_ids
            match_pct = int(((len(required) - len(missing)) / len(required)) * 100)
            matches.append({
                "id": recipe["id"],
                "title": recipe["title"],
                "description": recipe["description"],
                "prep_time": recipe["prep_time"],
                "required_ingredients": recipe["ingredients"],
                "missing_ingredients": list(missing),
                "match_percentage": match_pct,
                "can_cook_now": len(missing) == 0,
            })

        matches.sort(key=lambda x: x["match_percentage"], reverse=True)

        return json.dumps({
            "status": "success",
            "pantry_items_count": len(pantry_ids),
            "recipes": matches,
        }, indent=2)
    except Exception as e:
        return f"Error searching recipes: {str(e)}"


def search_online_recipes(query: str) -> str:
    """Searches online recipe database (TheMealDB) for real recipes, cooking instructions, and ingredients.

    Args:
        query: Recipe or dish search term (e.g., 'pasta', 'chicken', 'tacos', 'salad').

    Returns:
        A JSON string with online recipe details.
    """
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.themealdb.com/api/json/v1/{THEMEALDB_API_KEY}/search.php?s={encoded_query}"
        req = urllib.request.urlopen(url, timeout=6)
        data = json.loads(req.read().decode("utf-8"))
        meals = data.get("meals")

        if not meals:
            return json.dumps({"status": "not_found", "message": f"No online recipes found for '{query}'."})

        results = []
        for meal in meals[:3]:
            ingredients = []
            for i in range(1, 21):
                ing = meal.get(f"strIngredient{i}")
                measure = meal.get(f"strMeasure{i}")
                if ing and ing.strip():
                    ingredients.append(f"{measure.strip() if measure else ''} {ing.strip()}".strip())

            results.append({
                "id": meal.get("idMeal"),
                "name": meal.get("strMeal"),
                "category": meal.get("strCategory"),
                "area": meal.get("strArea"),
                "instructions": meal.get("strInstructions", "")[:300] + "...",
                "ingredients": ingredients,
                "image_url": meal.get("strMealThumb"),
            })

        return json.dumps({"status": "success", "query": query, "recipes": results}, indent=2)
    except Exception as e:
        return f"Error fetching online recipes: {str(e)}"


def geocode_address(address: str) -> str:
    """Converts a street address or location name into geographic coordinates (latitude and longitude).

    Args:
        address: The address or location string to geocode (e.g., '1600 Amphitheatre Pkwy, Mountain View, CA').

    Returns:
        A JSON string containing the formatted address and location coordinates (lat, lng).
    """
    try:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY", GOOGLE_MAPS_API_KEY)
        if not api_key:
            return "Error: GOOGLE_MAPS_API_KEY environment variable is missing."

        encoded = urllib.parse.quote(address)
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded}&key={api_key}"
        req = urllib.request.urlopen(url, timeout=6)
        res = json.loads(req.read().decode("utf-8"))

        if res.get("status") != "OK" or not res.get("results"):
            return json.dumps({"status": "error", "message": f"Could not geocode address: {address}"})

        first = res["results"][0]
        return json.dumps({
            "status": "success",
            "address": first.get("formatted_address"),
            "location": first.get("geometry", {}).get("location"),
        }, indent=2)
    except Exception as e:
        return f"Error during geocoding: {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "supermarket",
    radius_meters: float = 5000.0,
) -> str:
    """Finds nearby places of a given type near a geographic coordinate using Places API (New).

    Args:
        latitude: Center latitude coordinate.
        longitude: Center longitude coordinate.
        place_type: Type of place to search for (e.g., 'supermarket', 'grocery_store', 'bakery', 'restaurant').
        radius_meters: Search radius in meters (default: 5000 meters).

    Returns:
        A JSON string containing matching nearby places with name, formatted address, and location coordinates.
    """
    try:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY", GOOGLE_MAPS_API_KEY)
        if not api_key:
            return "Error: GOOGLE_MAPS_API_KEY environment variable is missing."

        url = "https://places.googleapis.com/v1/places:searchNearby"
        payload = json.dumps({
            "includedTypes": [place_type],
            "maxResultCount": 5,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                    },
                    "radius": float(radius_meters),
                }
            },
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
        }

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        res = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))

        places = []
        for p in res.get("places", []):
            places.append({
                "name": p.get("displayName", {}).get("text"),
                "address": p.get("formattedAddress"),
                "location": p.get("location"),
            })

        return json.dumps({
            "status": "success",
            "place_type": place_type,
            "places_count": len(places),
            "places": places,
        }, indent=2)
    except Exception as e:
        return f"Error searching nearby places: {str(e)}"


def generate_dish_image(tool_context: ToolContext, prompt: str) -> str:
    """Generates an image of a culinary dish or recipe item using gemini-3.1-flash-lite-image model in global region.

    Saves the generated image as an artifact and uploads bytes to public GCS bucket.

    Args:
        tool_context: ADK ToolContext used for saving artifacts.
        prompt: Detailed description of the dish to generate (e.g., 'Garlic Parmesan Spaghetti garnished with fresh herbs').

    Returns:
        A JSON string containing the public Cloud Storage HTTPS URL of the image.
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )

        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        image_part = None
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data:
                    image_part = part
                    break
            if image_part:
                break

        if not image_part or not image_part.inline_data:
            return "Error: No image content generated."

        image_bytes = image_part.inline_data.data
        mime_type = image_part.inline_data.mime_type or "image/jpeg"

        # 1. Save with tool_context.save_artifact
        filename = f"dish_{int(time.time())}.jpg"
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes directly to public GCS bucket
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(PUBLIC_IMAGE_BUCKET)
        object_name = f"dishes/{filename}"
        blob = bucket.blob(object_name)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{PUBLIC_IMAGE_BUCKET}/{object_name}"

        return json.dumps({
            "status": "success",
            "prompt": prompt,
            "filename": filename,
            "public_url": public_url,
        }, indent=2)

    except Exception as e:
        return f"Error generating dish image: {str(e)}"


# Memory-generation callback: extracts durable user facts/preferences after each turn
async def generate_memories_callback(callback_context: CallbackContext):
    if not getattr(callback_context, "memory_service", None):
        return None
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        print(f"Memory service callback skipped: {e}")
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Smart Pantry & Recipe Chef, an AI culinary assistant. "
        "You help users manage their pantry inventory, discover recipes based on available ingredients or web searches, "
        "find nearby grocery stores using Google Maps, execute Python code for nutrition/portion calculations in a sandbox, "
        "and generate visual food presentation images."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects.\n\n"
        "CRITICAL MEMORY & ALLERGY SAFETY DIRECTIVE:\n"
        "- Pay close attention to any user-stated food allergies (e.g. peanuts, tree nuts, shellfish, dairy, gluten, eggs, soy).\n"
        "- Always check preloaded user memories for stated allergies and dietary restrictions before recommending any recipe.\n"
        "- NEVER suggest recipes or ingredients that contain any of the user's remembered allergens.\n"
        "- Actively confirm and store any newly mentioned food allergies so they persist across future sessions.\n\n"
        "Tool usage guidelines: Use `list_pantry_items` to check available ingredients, `search_recipes_by_pantry` to check local matches, "
        "`search_online_recipes` to search web recipes via TheMealDB API, `geocode_address` to resolve locations, "
        "`find_nearby_places` to locate grocery stores, `generate_dish_image` for dish previews, "
        "`add_or_update_pantry_item` to track stock, and `remove_pantry_item` when items are consumed."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    tools=[
        list_pantry_items,
        add_or_update_pantry_item,
        remove_pantry_item,
        search_recipes_by_pantry,
        search_online_recipes,
        geocode_address,
        find_nearby_places,
        generate_dish_image,
        PreloadMemoryTool(),
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)


def memory_bank_service_builder():
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


app = App(
    root_agent=root_agent,
    name="app",
)
