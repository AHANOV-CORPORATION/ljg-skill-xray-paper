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

# Session management for Vercel compatibility
_session = None

def get_session():
    global _session
    if _session is None:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )
    return _session

async def close_session():
    global _session
    if _session:
        await _session.close()
        _session = None

def load_tokens(server_name):
    """Load tokens for the specified server"""
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
    """Send single request"""
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
        
        session = get_session()
        async with session.post(url, data=edata, headers=headers) as response:
            return response.status == 200
                
    except Exception as e:
        logger.error(f"Exception in send_request: {e}")
        return False

async def send_like_requests(uid, server_name, url, max_requests=30):
    """Send like requests with concurrency control"""
    try:
        region = server_name.upper()
        protobuf_message = create_protobuf_message(uid, region)
        if not protobuf_message:
            return 0

        encrypted_uid = encrypt_message(protobuf_message)
        if not encrypted_uid:
            return 0

        tokens = load_tokens(server_name)
        if not tokens:
            return 0

        # Limit requests for Vercel compatibility
        total_requests = min(max_requests, len(tokens))
        successful_requests = 0
        
        # Send requests concurrently but with limits
        tasks = []
        for i in range(total_requests):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful_requests = sum(1 for result in results if result is True)
        
        logger.info(f"Sent {successful_requests}/{total_requests} successful requests")
        return successful_requests
        
    except Exception as e:
        logger.error(f"Exception in send_like_requests: {e}")
        return 0

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

def get_player_info(encrypted_uid, server_name, token):
    """Get player information"""
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
        
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=10)
        if response.status_code != 200:
            return None
            
        hex_data = response.content.hex()
        binary = bytes.fromhex(hex_data)
        return decode_protobuf_response(binary)
        
    except Exception as e:
        logger.error(f"Error in get_player_info: {e}")
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

def extract_player_data(protobuf_info):
    """Extract player data from protobuf"""
    try:
        json_data = MessageToJson(protobuf_info)
        data = json.loads(json_data)
        account_info = data.get('AccountInfo', {})
        
        return {
            'likes': int(account_info.get('Likes', 0)),
            'uid': int(account_info.get('UID', 0)),
            'nickname': str(account_info.get('PlayerNickname', ''))
        }
    except Exception as e:
        logger.error(f"Error extracting player data: {e}")
        return {'likes': 0, 'uid': 0, 'nickname': ''}

@app.route('/like', methods=['GET'])
async def handle_like_request():
    """Handle like requests - optimized for Vercel"""
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

        before_info = get_player_info(encrypted_uid, server_name, token)
        if not before_info:
            return jsonify({"error": "Failed to retrieve player info", "status": 500}), 500

        before_data = extract_player_data(before_info)
        logger.info(f"Likes before: {before_data['likes']}")

        # Send like requests
        base_url = SERVER_CONFIGS[server_name]["base_url"]
        like_url = f"{base_url}/LikeProfile"
        
        successful_requests = await send_like_requests(uid, server_name, like_url)
        
        # Wait for server to process
        await asyncio.sleep(1)
        
        # Get updated player info
        after_info = get_player_info(encrypted_uid, server_name, token)
        if not after_info:
            return jsonify({"error": "Failed to retrieve updated player info", "status": 500}), 500

        after_data = extract_player_data(after_info)
        likes_given = after_data['likes'] - before_data['likes']
        status = 1 if likes_given > 0 else 2
        
        response_time = round(time.time() - start_time, 2)
        
        result = {
            "status": status,
            "LikesGivenByAPI": likes_given,
            "LikesBeforeCommand": before_data['likes'],
            "LikesAfterCommand": after_data['likes'],
            "PlayerNickname": after_data['nickname'],
            "UID": after_data['uid'],
            "SuccessfulRequests": successful_requests,
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
        "message": "FreeFire Like API - Optimized for Vercel",
        "credits": "Dev By jami",
        "discord": "https://discord.gg/b7XQpYeK2F",
        "endpoints": {
            "/like": "Send likes to player (uid, server_name params)",
            "/servers": "Get supported servers list",
            "/health": "Health check"
        }
    })

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "timestamp": time.time(),
        "servers_configured": len(SERVER_CONFIGS)
    })

# Vercel serverless compatibility
@app.before_request
async def before_request():
    """Initialize session before request"""
    get_session()

@app.after_request
async def after_request(response):
    """Cleanup after request for Vercel compatibility"""
    # Note: We don't close session immediately to allow connection reuse
    return response

# For Vercel serverless, we need to handle the async nature properly
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
