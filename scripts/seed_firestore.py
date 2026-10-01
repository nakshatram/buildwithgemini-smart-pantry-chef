"""
Seed script for Firestore pantry_items collection.
Hardcodes project ID string: qwiklabs-gcp-02-57f30fd7c82f
"""

from google.cloud import firestore

FIRESTORE_PROJECT_ID = "qwiklabs-gcp-02-57f30fd7c82f"

INITIAL_PANTRY_ITEMS = [
    {
        "item_id": "olive_oil",
        "name": "Extra Virgin Olive Oil",
        "quantity": 1,
        "unit": "bottle",
        "category": "Pantry",
        "expiration_date": "2027-01-15",
    },
    {
        "item_id": "eggs",
        "name": "Fresh Large Eggs",
        "quantity": 12,
        "unit": "count",
        "category": "Dairy",
        "expiration_date": "2026-10-25",
    },
    {
        "item_id": "tomatoes",
        "name": "Roma Tomatoes",
        "quantity": 6,
        "unit": "count",
        "category": "Produce",
        "expiration_date": "2026-10-10",
    },
    {
        "item_id": "pasta",
        "name": "Spaghetti Pasta",
        "quantity": 2,
        "unit": "boxes",
        "category": "Pantry",
        "expiration_date": "2027-06-01",
    },
    {
        "item_id": "garlic",
        "name": "Fresh Garlic Bulbs",
        "quantity": 3,
        "unit": "bulbs",
        "category": "Produce",
        "expiration_date": "2026-11-01",
    },
    {
        "item_id": "parmesan",
        "name": "Aged Parmesan Cheese",
        "quantity": 1,
        "unit": "block",
        "category": "Dairy",
        "expiration_date": "2026-11-20",
    },
]

def seed_database():
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    collection_ref = db.collection("pantry_items")
    
    print(f"Seeding pantry items into Firestore project '{FIRESTORE_PROJECT_ID}'...")
    for item in INITIAL_PANTRY_ITEMS:
        doc_id = item["item_id"]
        doc_ref = collection_ref.document(doc_id)
        doc_ref.set(item)
        print(f"  - Seeded item: {doc_id} -> {item['name']} ({item['quantity']} {item['unit']})")
    
    print("✅ Firestore seed complete!")

if __name__ == "__main__":
    seed_database()
