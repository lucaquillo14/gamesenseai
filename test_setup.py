import os
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

print("=== GameSense AI Setup Check ===")

# 1️⃣ Check .env (OpenAI API Key)
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ OpenAI API key missing — check .env file")
else:
    print("✅ OpenAI API key found")

# 2️⃣ Check Firebase Connection
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase connection successful")
except Exception as e:
    print("❌ Firebase connection failed:", e)

# 3️⃣ Test OpenAI connection
try:
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say 'GameSense AI is online!'"}]
    )
    print("✅ OpenAI test successful —", response.choices[0].message.content)
except Exception as e:
    print("❌ OpenAI test failed:", e)
