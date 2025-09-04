import os
import pandas as pd
import requests
import base64
import hashlib
import webbrowser
import secrets
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# --- Configuration ---
# IMPORTANT: Set these environment variables before running the script.
# You can get these from your Spotify Developer Dashboard.
# Example:
# export SPOTIPY_CLIENT_ID='your-client-id'
# export SPOTIPY_REDIRECT_URI='http://localhost:8888/callback'
# Note: SPOTIPY_CLIENT_SECRET is NOT needed for the PKCE flow.

CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')
SCOPE = 'user-top-read'
OUTPUT_FILENAME = 'spotify_listening_history.csv'

# --- Spotify API Endpoints ---
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
API_BASE_URL = 'https://api.spotify.com/v1/'

# This will be used to store the authorization code received from Spotify
auth_code_holder = {}

def generate_code_verifier_and_challenge():
    """Generates a code verifier and its corresponding code challenge for PKCE."""
    code_verifier = secrets.token_urlsafe(64)
    hashed = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(hashed).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

class CallbackHandler(BaseHTTPRequestHandler):
    """A simple HTTP server handler to catch the Spotify callback."""
    def do_GET(self):
        global auth_code_holder
        # Parse the query parameters from the request
        if 'code' in self.path:
            query = self.path.split('?')[1]
            params = dict(p.split('=') for p in query.split('&'))
            auth_code_holder['code'] = params['code']
            
            # Respond to the browser
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h1>Authentication successful!</h1><p>You can close this window now.</p>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>Authentication failed.</h1><p>Please try again.</p>")

def start_callback_server():
    """Starts a temporary local server to handle the OAuth callback."""
    server = HTTPServer(('localhost', 8888), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    print("🚀 Local server started on port 8888 to catch Spotify callback...")
    return server

def stop_callback_server(server):
    """Shuts down the local server."""
    server.shutdown()
    print("🛑 Local server stopped.")

def authenticate_spotify():
    """
    Manually handles the Spotify Authentication Code Flow with PKCE.
    
    Returns:
        str: An access token for making API requests. Returns None if authentication fails.
    """
    if not all([CLIENT_ID, REDIRECT_URI]):
        print("🔴 Error: Make sure you have set SPOTIPY_CLIENT_ID and SPOTIPY_REDIRECT_URI.")
        return None

    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    
    # 1. Start local server and construct authorization URL
    server = start_callback_server()
    auth_params = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPE,
        'code_challenge_method': 'S256',
        'code_challenge': code_challenge,
    }
    auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"
    
    # 2. Open browser for user authorization
    print("👉 Opening your browser for Spotify authorization...")
    webbrowser.open(auth_url)
    
    # 3. Wait for the authorization code from the callback
    while 'code' not in auth_code_holder:
        pass
    stop_callback_server(server)
    
    auth_code = auth_code_holder.get('code')
    if not auth_code:
        print("🔴 Could not retrieve authorization code.")
        return None

    # 4. Exchange authorization code for an access token
    token_payload = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'code_verifier': code_verifier,
    }
    
    try:
        token_res = requests.post(TOKEN_URL, data=token_payload)
        token_res.raise_for_status()
        token_data = token_res.json()
        print("✅ Successfully authenticated with Spotify using PKCE!")
        return token_data.get('access_token')
    except requests.exceptions.RequestException as e:
        print(f"🔴 Failed to get access token: {e}")
        print(f"   Response: {token_res.text}")
        return None

def get_top_tracks(access_token, time_range='medium_term', limit=50):
    """Fetches the user's top tracks using a direct API call."""
    print(f"\nFetching top {limit} tracks for time range: {time_range}...")
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'time_range': time_range, 'limit': limit}
    try:
        res = requests.get(API_BASE_URL + 'me/top/tracks', headers=headers, params=params)
        res.raise_for_status()
        results = res.json()
        print(f"✅ Found {len(results['items'])} tracks.")
        return results['items']
    except requests.exceptions.RequestException as e:
        print(f"🔴 Could not fetch top tracks: {e}")
        return []

def get_audio_features(access_token, track_ids):
    """Fetches audio features using a direct API call."""
    print("Fetching audio features for tracks...")
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'ids': ','.join(track_ids)}
    try:
        res = requests.get(API_BASE_URL + 'audio-features', headers=headers, params=params)
        res.raise_for_status()
        features = res.json()['audio_features']
        print("✅ Audio features fetched successfully.")
        return features
    except requests.exceptions.RequestException as e:
        print(f"🔴 Could not fetch audio features: {e}")
        return []

def process_and_save_data(tracks, audio_features):
    """Cleans, structures, and saves the track and audio feature data to a CSV file."""
    if not tracks or not audio_features:
        print("🔴 No data to process. Exiting.")
        return

    print("\nProcessing and structuring data...")
    all_tracks_data = []
    features_dict = {f['id']: f for f in audio_features if f}

    for track in tracks:
        track_info = {
            'track_id': track['id'],
            'track_name': track['name'],
            'artist_name': ', '.join([artist['name'] for artist in track['artists']]),
            'album_name': track['album']['name'],
            'popularity': track['popularity'],
            'duration_ms': track['duration_ms']
        }
        features = features_dict.get(track['id'])
        if features:
            track_info.update({
                'danceability': features.get('danceability'),
                'energy': features.get('energy'),
                'key': features.get('key'),
                'loudness': features.get('loudness'),
                'mode': features.get('mode'),
                'speechiness': features.get('speechiness'),
                'acousticness': features.get('acousticness'),
                'instrumentalness': features.get('instrumentalness'),
                'liveness': features.get('liveness'),
                'valence': features.get('valence'),
                'tempo': features.get('tempo'),
            })
        all_tracks_data.append(track_info)

    df = pd.DataFrame(all_tracks_data)
    try:
        df.to_csv(OUTPUT_FILENAME, index=False)
        print(f"✅ Data successfully saved to '{OUTPUT_FILENAME}'")
        print(f"Total tracks processed: {len(df)}")
    except Exception as e:
        print(f"🔴 Failed to save data to CSV: {e}")

def main():
    """Main function to run the data extraction process."""
    print("--- Spotify Mind Map: Phase 1 - Data Extraction (Manual PKCE) ---")
    
    # 1. Authenticate
    token = authenticate_spotify()
    
    if token:
        # 2. Extract Data
        top_tracks = get_top_tracks(token)
        
        if top_tracks:
            track_ids = [track['id'] for track in top_tracks]
            
            # 3. Get Audio Features
            audio_features = get_audio_features(token, track_ids)
            
            # 4. Clean, Structure, and Save
            process_and_save_data(top_tracks, audio_features)

if __name__ == '__main__':
    main()

