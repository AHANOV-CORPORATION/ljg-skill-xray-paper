from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import os
from proto import like_pb2
from proto import like_count_pb2
from proto import uid_generator_pb2
from google.protobuf.message import DecodeError
import logging
from concurrent.futures import ThreadPoolExecutor
import time

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Server configurations
SERVER_CONFIGS = {
    "IND": {"token_file": "token_ind.json", "base_url": "https://client.ind.freefiremobile.com"},
    "BR": {"token_file": "token_br.json", "base_url": "https://client.us.freefiremobile.com"},
    "US": {"token_file": "token_br.json", "base_url": "https://client.us.freefiremobile.com"},
    "SAC": {"token_file": "token_br.json", "base_url": "https://client.us.freefiremobile.com"},
    "NA": {"token_file": "token_br.json", "base_url": "https://client.us.freefiremobile.com"},
    "BD": {"token_file": "token_bd.json", "base_url": "https://clientbp.ggblueshark.com"},
    "ID": {"token_file": "token_id.json", "base_url": "https://clientid.freefiremobile.com"},
    "VN": {"token_file": "token_vn.json", "base_url": "https://clientvn.freefiremobile.com"},
    "CIS": {"token_file": "token_cis.json", "base_url": "https://clientcis.freefiremobile.com"},
    "PK": {"token_file": "token_pk.json", "base_url": "https://clientpk.freefiremobile.com"},
    "SG": {"token_file": "token_sg.json", "base_url": "https://clientsg.freefiremobile.com"},
    "EU": {"token_file": "token_eu.json", "base_url": "https://clienteu.freefiremobile.com"},
    "TW": {"token_file": "token_tw.json", "base_url": "https://clienttw.freefiremobile.com"},
    "ME": {"token_file": "token_me.json", "base_url": "https://clientme.freefiremobile.com"},
    "TH": {"token_file": "token_th.json", "base_url": "https://clientth.freefiremobile.com"}
}

# Encryption constants
ENCRYPTION_KEY = b'Yg&tc%DEuh6%Zc^8'
ENCRYPTION_IV = b'6oyZDr22E3ychjM%'

# Global session for connection reuse
session = None

def get_session():
    global session
    if session is None:
        session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=20),
            timeout=aiohttp.ClientTimeout(total=30)
        )
    return session

def load_tokens(server_name):
    """Load tokens for the specified server with caching"""
    try:
        server_name = server_name.upper()
        if server_name not in SERVER_CONFIGS:
            raise ValueError(f"Unsupported server: {server_name}")
        
        token_file = SERVER_CONFIGS[server_name]["token_file"]
        if not os.path.exists(token_file):
            raise FileNotFoundError(f"Token file not found: {token_file}")
        
        with open(token_file, "r") as f:
            tokens = json.load(f)
        
        if not tokens:
            raise ValueError(f"No tokens found in {token_file}")
        
        return tokens
    except Exception as e:
        logger.error(f"Error loading tokens for server {server_name}: {e}")
        return None

def encrypt_message(plaintext):
    """Encrypt message using AES CBC mode"""
    try:
        cipher = AES.new(ENCRYPTION_KEY, AES.MODE_CBC, ENCRYPTION_IV)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        logger.error(f"Error encrypting message: {e}")
        return None

def create_protobuf_message(user_id, region):
    """Create protobuf message for like request"""
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        logger.error(f"Error creating protobuf message: {e}")
        return None

async def send_request(encrypted_uid, token, url):
    """Send single request with connection reuse"""
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB50"
        }
        
        current_session = get_session()
        async with current_session.post(url, data=edata, headers=headers) as response:
            if response.status == 200:
                return await response.text()
            else:
                logger.warning(f"Request failed with status: {response.status}")
                return None
                
    except Exception as e:
        logger.error(f"Exception in send_request: {e}")
        return None

async def send_batch_requests(uid, server_name, url, batch_size=50):
    """Send requests in batches to avoid overwhelming the server"""
    try:
        region = server_name.upper()
        protobuf_message = create_protobuf_message(uid, region)
        if not protobuf_message:
            return None

        encrypted_uid = encrypt_message(protobuf_message)
        if not encrypted_uid:
            return None

        tokens = load_tokens(server_name)
        if not tokens:
            return None

        # Use all available tokens but limit concurrent requests
        total_requests = min(len(tokens) * 2, 100)  # Limit to reasonable number
        successful_requests = 0
        
        for i in range(0, total_requests, batch_size):
            batch_tokens = [tokens[j % len(tokens)]["token"] for j in range(i, min(i + batch_size, total_requests))]
            
            tasks = [send_request(encrypted_uid, token, url) for token in batch_tokens]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Count successful requests
            successful_requests += sum(1 for result in results if result is not None)
            
            # Small delay between batches
            if i + batch_size < total_requests:
                await asyncio.sleep(0.1)
        
        logger.info(f"Sent {successful_requests}/{total_requests} successful requests")
        return successful_requests
        
    except Exception as e:
        logger.error(f"Exception in send_batch_requests: {e}")
        return None

def create_uid_protobuf(uid):
    """Create protobuf message for UID lookup"""
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        logger.error(f"Error creating uid protobuf: {e}")
        return None

def encrypt_uid(uid):
    """Encrypt UID for player info lookup"""
    protobuf_data = create_uid_protobuf(uid)
    if not protobuf_data:
        return None
    return encrypt_message(protobuf_data)

def make_player_info_request(encrypted_uid, server_name, token):
    """Make request to get player information"""
    try:
        server_name = server_name.upper()
        if server_name not in SERVER_CONFIGS:
            raise ValueError(f"Unsupported server: {server_name}")
        
        base_url = SERVER_CONFIGS[server_name]["base_url"]
        url = f"{base_url}/GetPlayerPersonalShow"
        
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB50"
        }
        
        # Use requests with connection pooling
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=10)
        hex_data = response.content.hex()
        binary = bytes.fromhex(hex_data)
        return decode_protobuf_response(binary)
        
    except Exception as e:
        logger.error(f"Error in make_player_info_request: {e}")
        return None

def decode_protobuf_response(binary):
    """Decode protobuf response"""
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        logger.error(f"Error decoding Protobuf data: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during protobuf decoding: {e}")
        return None

@app.route('/like', methods=['GET'])
def handle_like_request():
    """Handle like requests with improved performance"""
    start_time = time.time()
    
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    
    if not uid or not server_name:
        return jsonify({"error": "UID and server_name are required", "status": 400}), 400

    if server_name not in SERVER_CONFIGS:
        return jsonify({"error": f"Unsupported server. Available: {', '.join(SERVER_CONFIGS.keys())}", "status": 400}), 400

    try:
        # Load tokens
        tokens = load_tokens(server_name)
        if not tokens:
            return jsonify({"error": "Failed to load tokens for server", "status": 500}), 500

        token = tokens[0]['token']
        
        # Get initial player info
        encrypted_uid = encrypt_uid(uid)
        if not encrypted_uid:
            return jsonify({"error": "Encryption failed", "status": 500}), 500

        before_info = make_player_info_request(encrypted_uid, server_name, token)
        if not before_info:
            return jsonify({"error": "Failed to retrieve player info", "status": 500}), 500

        # Convert to JSON and extract data
        try:
            before_json = MessageToJson(before_info)
            before_data = json.loads(before_json)
            before_likes = before_data.get('AccountInfo', {}).get('Likes', 0)
            before_likes = int(before_likes) if before_likes else 0
        except Exception as e:
            logger.error(f"Error processing initial data: {e}")
            before_likes = 0

        logger.info(f"Likes before: {before_likes}")

        # Send like requests
        base_url = SERVER_CONFIGS[server_name]["base_url"]
        like_url = f"{base_url}/LikeProfile"
        
        # Run async requests
        successful_requests = asyncio.run(send_batch_requests(uid, server_name, like_url))
        
        # Small delay to ensure server processes likes
        time.sleep(1)
        
        # Get updated player info
        after_info = make_player_info_request(encrypted_uid, server_name, token)
        if not after_info:
            return jsonify({"error": "Failed to retrieve updated player info", "status": 500}), 500

        # Convert to JSON and extract data
        try:
            after_json = MessageToJson(after_info)
            after_data = json.loads(after_json)
            after_likes = int(after_data.get('AccountInfo', {}).get('Likes', 0))
            player_uid = int(after_data.get('AccountInfo', {}).get('UID', 0))
            player_name = str(after_data.get('AccountInfo', {}).get('PlayerNickname', ''))
        except Exception as e:
            logger.error(f"Error processing updated data: {e}")
            return jsonify({"error": "Failed to process player data", "status": 500}), 500

        likes_given = after_likes - before_likes
        status = 1 if likes_given > 0 else 2
        
        response_time = round(time.time() - start_time, 2)
        
        result = {
            "status": status,
            "LikesGivenByAPI": likes_given,
            "LikesBeforeCommand": before_likes,
            "LikesAfterCommand": after_likes,
            "PlayerNickname": player_name,
            "UID": player_uid,
            "SuccessfulRequests": successful_requests or 0,
            "ResponseTime": f"{response_time}s",
            "Server": server_name
        }
        
        logger.info(f"Request completed in {response_time}s - Likes given: {likes_given}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return jsonify({"error": str(e), "status": 500}), 500

@app.route("/servers", methods=["GET"])
def get_servers():
    """Get list of supported servers"""
    return jsonify({
        "supported_servers": list(SERVER_CONFIGS.keys()),
        "total_servers": len(SERVER_CONFIGS)
    })

@app.route("/", methods=["GET"])
def home():
    """Home endpoint"""
    return jsonify({
        "message": "FreeFire Like API - Optimized Version",
        "credits": "Dev By jami",
        "discord": "https://discord.gg/b7XQpYeK2F",
        "endpoints": {
            "/like": "Send likes to player (uid, server_name params)",
            "/servers": "Get supported servers list"
        }
    })

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": time.time()})

@app.teardown_appcontext
def close_session(exception=None):
    """Close aiohttp session on app teardown"""
    global session
    if session:
        asyncio.run(session.close())
        session = None

if __name__ == '__main__':
    # Production configuration
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=False,
        threaded=True
    )