# test_oauth.py - Simple OAuth test
import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow

load_dotenv()

def main():
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    redirect_uri = 'http://localhost:8001/oauth/gmail/callback'
    
    scopes = [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify'
    ]
    
    print(f"Client ID: {client_id[:20]}...")
    print(f"Redirect URI: {redirect_uri}")
    
    # Create the flow
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }
    
    flow = Flow.from_client_config(client_config, scopes=scopes)
    flow.redirect_uri = redirect_uri
    
    # Generate URL
    auth_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        login_hint='santhosh27122004@gmail.com'
    )
    
    print(f"\n✅ SUCCESS! Generated OAuth URL:")
    print(f"{auth_url}")
    print(f"\n👉 Copy this URL and paste it in your browser")
    print(f"State: {state}")

if __name__ == "__main__":
    main()