# db_manager.py
# Multiple processes (e.g., web workers)  will reimport but in one process it will reuse
from pymongo import MongoClient
import atexit
from typing import Optional
from pymongo.collection import Collection
import streamlit as st

# --- Configuration ---
DATABASE_NAME: str = "poker_hands_db"
COLLECTION_NAME: str = "hand_logs"

# Global variables to hold the client and collection
mongo_client: Optional[MongoClient] = None
HANDS_COLLECTION: Optional[Collection] = None


def initialize_mongodb():
    """Initializes the MongoDB client and connection pool."""
    global mongo_client, HANDS_COLLECTION

    try:
        # Create the Singleton Client instance
        mongo_client = MongoClient(st.secrets["MONGO_URI"])
        db = mongo_client[DATABASE_NAME]
        HANDS_COLLECTION = db[COLLECTION_NAME]

        # Register the cleanup function to ensure closure on exit
        atexit.register(close_mongodb_connection)

        print(f"✅ MongoDB connection established to {DATABASE_NAME}.")

    except Exception as e:
        print(f"❌ Error connecting to MongoDB: {e}")
        HANDS_COLLECTION = None  # Set to None on failure


def close_mongodb_connection():
    """Closes the MongoDB client connection gracefully."""
    global mongo_client
    if mongo_client:
        mongo_client.close()
        print("🔌 MongoDB connection closed gracefully.")


# Initialize the connection when this module is imported
initialize_mongodb()
