#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
UAE NOC VALIDATOR APPLICATION 
═══════════════════════════════════════════════════════════════════════════════

Purpose:
    This application validates UAE No Objection Certificates (NOCs) using 
    SAP Document Information Extraction (DOX) service. It extracts key 
    information from PDF documents and provides confidence scores.

Key Features:
    - PDF document upload and processing
    - AI-powered data extraction using SAP DOX
    - Confidence score calculation with weighted fields
    - Real-time processing status updates
    - Interactive dashboard for results visualization

Version: 2.0.0
Author: Deepasri M Prasad
"""

# ═══════════════════════════════════════════════════════════════════════════
# IMPORTS - External Libraries and Modules
# ═══════════════════════════════════════════════════════════════════════════

import os              # Operating system interface for file/environment operations
import io              # Input/output operations for file handling
import json            # JSON encoding/decoding for configuration files
import time            # Time-related functions for polling delays
import base64          # Base64 encoding/decoding for file uploads
import requests        # HTTP library for API calls to SAP DOX
import pandas as pd    # Data manipulation library for tables
import plotly.graph_objects as go    # Advanced plotting for gauge charts
import plotly.express as px          # Simple plotting for bar charts
import PyPDF2          # PDF manipulation library for page splitting
import fitz            # PyMuPDF - PDF rendering and image extraction
import threading       # Multi-threading for async document processing
import uuid            # Unique identifier generation for jobs
from datetime import datetime         # Date/time handling
from pathlib import Path              # Object-oriented filesystem paths
from flask import Flask, jsonify, request  # Web framework for API
from io import BytesIO                # In-memory binary streams
from dotenv import load_dotenv        # Environment variable loader
from concurrent.futures import ThreadPoolExecutor, as_completed  # Parallel processing

# Dash Framework - Interactive web dashboard components
import dash
from dash import Dash, html, dcc, dash_table, Input, Output, State, no_update, callback_context, ALL
from dash.exceptions import PreventUpdate

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION LOADING
# ═══════════════════════════════════════════════════════════════════════════

# Load environment variables from .env file (if exists)
# This file contains sensitive credentials like API keys
load_dotenv()

# Load additional configuration from config.json
# This file contains non-sensitive settings like thresholds and weights
CONFIG_PATH = Path("config.json")
CONFIG = {}
if CONFIG_PATH.exists():
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
        print("✔️ Loaded config.json")

# ═══════════════════════════════════════════════════════════════════════════
# SAP DOX CREDENTIALS AUTO-LOADING
# ═══════════════════════════════════════════════════════════════════════════
# The application supports multiple ways to provide SAP DOX credentials:
# 1. Environment variables (.env file)
# 2. Cloud Foundry service binding (VCAP_SERVICES)
# 3. Service key JSON file
# 4. config.json file

def parse_service_key(service_key_data):
    """
    Parse SAP DOX service key and extract credentials
    
    A service key is a JSON object containing connection details for SAP DOX.
    This function extracts:
        - UAA URL: Authentication endpoint
        - Client ID: Application identifier
        - Client Secret: Application password
        - DOX Base URL: API endpoint for document processing
    
    Args:
        service_key_data (dict): Service key JSON data
        
    Returns:
        dict: Extracted credentials with keys:
              UAA_URL, CLIENT_ID, CLIENT_SECRET, DOX_BASE_URL
    """
    credentials = {}
    
    # Extract authentication details from UAA section
    if "uaa" in service_key_data:
        uaa = service_key_data["uaa"]
        uaa_base_url = uaa.get("url", "")
        # Construct OAuth token endpoint
        credentials["UAA_URL"] = f"{uaa_base_url}/oauth/token"
        credentials["CLIENT_ID"] = uaa.get("clientid", "")
        credentials["CLIENT_SECRET"] = uaa.get("clientsecret", "")
    
    # Extract DOX API endpoint
    base_url = service_key_data.get("url", "")
    swagger_path = service_key_data.get("swagger", "/document-information-extraction/v1/")
    api_path = swagger_path.rstrip("/")
    credentials["DOX_BASE_URL"] = f"{base_url}{api_path}"
    
    return credentials


def load_from_vcap_services():
    """
    Load credentials from VCAP_SERVICES environment variable
    
    In Cloud Foundry (SAP BTP), when you bind a service to your application,
    the connection details are automatically provided via VCAP_SERVICES.
    This is a JSON string containing all bound service credentials.
    
    Returns:
        dict: Extracted credentials or empty dict if not found
    """
    # Get VCAP_SERVICES from environment (Cloud Foundry sets this automatically)
    vcap_services_str = os.getenv("VCAP_SERVICES", "{}")
    
    try:
        vcap_services = json.loads(vcap_services_str)
        
        # Try multiple possible service names for SAP DOX
        service_names = ["document-information-extraction", "dox", "aiservices-dox"]
        
        for service_name in service_names:
            if service_name in vcap_services:
                instances = vcap_services[service_name]
                if instances and len(instances) > 0:
                    service_key = instances[0].get("credentials", {})
                    print(f"✔️ Found DOX service in VCAP_SERVICES: {service_name}")
                    return parse_service_key(service_key)
        
        # Fallback: Look for any service with DOX-like structure
        for service_type, instances in vcap_services.items():
            if instances and len(instances) > 0:
                creds = instances[0].get("credentials", {})
                # Check if it has UAA and swagger (typical DOX service structure)
                if "uaa" in creds and "swagger" in creds:
                    print(f"✔️ Found DOX-like service: {service_type}")
                    return parse_service_key(creds)
        
    except json.JSONDecodeError:
        pass  # VCAP_SERVICES not available or invalid JSON
    
    return {}


def load_from_service_key_file():
    """
    Load credentials from a local service key JSON file
    
    During development, you can download a service key from SAP BTP
    and place it in the app directory. This function looks for common
    file names.
    
    Returns:
        dict: Extracted credentials or empty dict if file not found
    """
    # Try multiple common file names
    for file_name in ["service_key.json", "credentials.json", "dox_credentials.json"]:
        path = Path(file_name)
        if path.exists():
            try:
                with open(path, "r") as f:
                    service_key = json.load(f)
                print(f"✔️ Loaded credentials from {file_name}")
                return parse_service_key(service_key)
            except Exception as e:
                print(f"⚠️ Error loading {file_name}: {e}")
    
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# CREDENTIAL LOADING PRIORITY ORDER
# ═══════════════════════════════════════════════════════════════════════════
# Priority (highest to lowest):
# 1. Environment variables (from .env or system) - Most secure for production
# 2. VCAP_SERVICES (Cloud Foundry binding) - Automatic in BTP
# 3. Service key JSON file - Convenient for local development
# 4. config.json - Fallback option

auto_credentials = {}

# Step 1: Check VCAP_SERVICES (Cloud Foundry deployment)
if os.getenv("VCAP_SERVICES"):
    auto_credentials = load_from_vcap_services()
    if auto_credentials:
        print("✔️ Loaded credentials from VCAP_SERVICES (Cloud Foundry)")

# Step 2: Check for service key file (local development)
if not auto_credentials:
    auto_credentials = load_from_service_key_file()

# ═══════════════════════════════════════════════════════════════════════════
# SAP DOX CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
# Load SAP DOX credentials with priority: env vars > auto-loaded > config.json

UAA_URL = (
    os.getenv("UAA_URL") or           # From .env or system environment
    auto_credentials.get("UAA_URL") or # From VCAP_SERVICES or service_key.json
    CONFIG.get("uaa_url", "")          # From config.json (fallback)
)

DOX_BASE_URL = (
    os.getenv("DOX_BASE_URL") or 
    auto_credentials.get("DOX_BASE_URL") or 
    CONFIG.get("dox_base_url", "")
)

CLIENT_ID = (
    os.getenv("CLIENT_ID") or 
    auto_credentials.get("CLIENT_ID") or 
    CONFIG.get("client_id", "")
)

CLIENT_SECRET = (
    os.getenv("CLIENT_SECRET") or 
    auto_credentials.get("CLIENT_SECRET") or 
    CONFIG.get("client_secret", "")
)

# ═══════════════════════════════════════════════════════════════════════════
# APPLICATION CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Server configuration
APP_PORT = int(os.getenv("PORT", CONFIG.get("port", 7070)))
APP_HOST = os.getenv("HOST", CONFIG.get("host", "0.0.0.0"))
DEBUG_MODE = str(os.getenv("DEBUG", CONFIG.get("debug", "false"))).lower() == "true"
APP_VERSION = CONFIG.get("version", "2.0.0")

# Validate that all required configuration is present
config_valid = all([UAA_URL, DOX_BASE_URL, CLIENT_ID, CLIENT_SECRET])

if not config_valid:
    print("⚠️ WARNING: Missing SAP DOX configuration.")
    print("Options to provide credentials:")
    print("  1. Set environment variables in .env file")
    print("  2. Place service_key.json in the app directory")
    print("  3. Bind service in Cloud Foundry (VCAP_SERVICES)")
    print("  4. Add credentials to config.json")
    print("Required: UAA_URL, DOX_BASE_URL, CLIENT_ID, CLIENT_SECRET")
else:
    print(f"✔️ SAP DOX configured:")
    print(f"   UAA: {UAA_URL[:50]}...")
    print(f"   DOX: {DOX_BASE_URL}")

# ═══════════════════════════════════════════════════════════════════════════
# DIRECTORY SETUP
# ═══════════════════════════════════════════════════════════════════════════
# Create output directory for caching client and schema information

LOCAL_DIR = Path("./output")
LOCAL_DIR.mkdir(exist_ok=True)  # Create if doesn't exist

# Cache files to avoid repeated API calls
CLIENT_FILE = LOCAL_DIR / "dox_client.json"    # Stores DOX client ID
SCHEMA_FILE = LOCAL_DIR / "dox_schema.json"    # Stores schema ID

# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL STATE FOR ASYNC PROCESSING
# ═══════════════════════════════════════════════════════════════════════════
# Since document processing can take time, we use background threads.
# This dictionary stores all active and completed jobs.

processing_jobs = {}      # Dictionary to store ProcessingJob objects
job_lock = threading.Lock()  # Thread-safe lock for accessing processing_jobs
progress_lock = threading.Lock()  # Thread-safe lock for progress updates

class ProcessingJob:
    """
    Represents a single document processing job
    
    Each time a user uploads a document, a new ProcessingJob is created
    with a unique ID. This object tracks the processing status, logs,
    and results in a thread-safe manner.
    
    Attributes:
        job_id (str): Unique identifier (UUID)
        status (str): Current status (queued, processing, completed, failed)
        progress (int): Progress percentage (0-100)
        logs (list): List of log messages
        result (dict): Processing result data
        error (str): Error message if failed
        created_at (datetime): When the job was created
        updated_at (datetime): When the job was last updated
    """
    
    def __init__(self, job_id):
        """Initialize a new processing job"""
        self.job_id = job_id
        self.status = "queued"  # Initial status
        self.progress = 0       # 0% progress
        self.logs = []          # Empty log list
        self.result = None      # No result yet
        self.error = None       # No error yet
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def add_log(self, message):
        """
        Add a timestamped log entry
        
        This method is thread-safe and updates both the internal log
        and prints to console for monitoring.
        
        Args:
            message (str): Log message to add
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        self.updated_at = datetime.now()
        print(entry)  # Also print to server console
    
    def to_dict(self):
        """
        Convert job to dictionary format for JSON serialization
        
        Used by API endpoints to return job status.
        
        Returns:
            dict: Job data in dictionary format
        """
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "logs": self.logs,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA LOADING
# ═══════════════════════════════════════════════════════════════════════════
# The schema defines what fields to extract from documents.
# It's stored in a JSON file and loaded at application startup.

def load_schema():
    """
    Load document schema from JSON file
    
    The schema defines:
        - What fields to extract (e.g., applicationNumber, ownerName)
        - Field descriptions (user-friendly labels)
        - Which fields are mandatory
        - Field data types and validation rules
    
    The function tries multiple schema files in order of preference.
    
    Returns:
        tuple: (schema_data, all_fields, mandatory_fields, friendly_labels, schema_path)
            - schema_data (dict): Full schema JSON
            - all_fields (list): List of field names to extract
            - mandatory_fields (list): Fields that must be present
            - friendly_labels (dict): Field name -> User-friendly description
            - schema_path (Path): Path to loaded schema file
    """
    # Try multiple schema file locations
    schema_paths = [
        Path("schemas/uae_noc_schema_v2.json"),
        Path("schemas/uae_noc_schema_custom_runtime_v2.json")
    ]
    
    schema_data = {}
    schema_path_found = None
    all_fields, mandatory_fields, friendly_labels = [], [], {}
    
    # Try each schema file until one loads successfully
    for schema_path in schema_paths:
        try:
            if schema_path.exists():
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_data = json.load(f)
                
                # Extract field definitions from schema
                for fdef in schema_data.get("headerFields", []):
                    name = fdef.get("name")  # Technical field name
                    desc = fdef.get("description", name)  # Human-readable description
                    
                    # Skip runtime-only fields (not extractable from documents)
                    if "runtime field" not in desc.lower():
                        all_fields.append(name)
                    
                    # Store friendly labels for UI display
                    friendly_labels[name] = desc
                
                # Load mandatory fields from config or use defaults
                # These are the critical fields that MUST be present
                mandatory_fields = CONFIG.get("mandatory_fields", [
                    "applicationNumber",  # NOC reference number
                    "issuingAuthority",   # Government body that issued NOC
                    "ownerName",          # Person/company name on NOC
                    "issueDate"           # When NOC was issued
                ])
                
                print(f"✔️ Schema loaded: {schema_path.name} ({len(all_fields)} extractable fields)")
                schema_path_found = schema_path
                break  # Stop trying other files
                
        except Exception as e:
            print(f"⚠️ Error loading {schema_path}: {e}")
            continue  # Try next schema file
    
    # Fallback configuration if no schema file found
    # This ensures the app can still run with minimal functionality
    if not all_fields:
        print("⚠️ Using fallback schema configuration")
        all_fields = ["applicationNumber", "issuingAuthority", "ownerName", "issueDate", "documentStatus"]
        friendly_labels = {k: k for k in all_fields}  # Use field name as label
        mandatory_fields = ["applicationNumber", "issuingAuthority", "ownerName", "issueDate"]
    
    return schema_data, all_fields, mandatory_fields, friendly_labels, schema_path_found

# Load schema at application startup
# These global variables are used throughout the application
SCHEMA_DATA, ALL_FIELDS, MANDATORY_FIELDS, FRIENDLY_LABELS, SCHEMA_FILE_PATH = load_schema()

# ═══════════════════════════════════════════════════════════════════════════
# SAP DOX API FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════
# These functions handle communication with the SAP Document Information
# Extraction (DOX) service via REST API.

def get_token():
    """
    Get OAuth2 authentication token from SAP UAA (User Account and Authentication)
    
    SAP services use OAuth2 for authentication. Before making any API calls,
    we need to get an access token using client credentials flow.
    
    Flow:
        1. Send POST request to UAA with client_id and client_secret
        2. UAA validates credentials
        3. UAA returns access_token (valid for ~12 hours typically)
        4. Use this token in Authorization header for subsequent requests
    
    Returns:
        str: Access token if successful, None if failed
    """
    if not config_valid:
        return None
        
    try:
        # OAuth2 client credentials grant request
        r = requests.post(
            UAA_URL,
            data={"grant_type": "client_credentials"},
            auth=(CLIENT_ID, CLIENT_SECRET),  # HTTP Basic Auth
            timeout=30,
        )
        r.raise_for_status()  # Raise exception for 4xx/5xx status codes
        return r.json()["access_token"]
        
    except Exception as e:
        print(f"⚠️ Token fetch failed: {e}")
        return None

def get_or_create_client(token):
    """
    Get existing DOX client or create a new one
    
    In SAP DOX, a "client" is a logical container for documents and schemas.
    Each tenant/application should have its own client ID.
    
    This function:
        1. Checks local cache for existing client ID
        2. If not cached, queries DOX for existing clients
        3. If no clients exist, creates a new one
        4. Caches the client ID for future use
    
    Args:
        token (str): OAuth access token
        
    Returns:
        str: Client ID if successful, None if failed
    """
    try:
        DOX_CLIENT_URL = f"{DOX_BASE_URL}/clients"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Check cache first (avoids unnecessary API calls)
        if CLIENT_FILE.exists():
            cached = json.loads(CLIENT_FILE.read_text())
            print(f"✔️ Using cached client: {cached['clientId']}")
            return cached["clientId"]

        # Query existing clients
        print("📡 Checking existing DOX clients...")
        resp = requests.get(DOX_CLIENT_URL, headers=headers, params={"limit": 10}, timeout=30)
        
        if resp.status_code == 200:
            payload = resp.json().get("payload", [])
            if payload:
                # Use the first existing client
                client_id = payload[0]["clientId"]
                # Cache it for next time
                CLIENT_FILE.write_text(json.dumps({"clientId": client_id}, indent=2))
                print(f"✔️ Existing DOX client found: {client_id}")
                return client_id

        # No existing client found, create a new one
        new_client_id = CONFIG.get("client_name", "uae_noc_client")
        payload = {
            "value": [{
                "clientId": new_client_id,
                "clientName": "UAE NOC Validator Client"
            }]
        }
        
        print("📦 Creating new DOX client...")
        create_resp = requests.post(DOX_CLIENT_URL, headers=headers, json=payload, timeout=30)
        
        if create_resp.status_code not in (200, 201):
            print(f"❌ Client creation failed: {create_resp.status_code}")
            return None
            
        # Extract the created client ID
        created_id = create_resp.json().get("payload", [{}])[0].get("clientId", new_client_id)
        
        # Cache for future use
        CLIENT_FILE.write_text(json.dumps({"clientId": created_id}, indent=2))
        print(f"✔️ Created new DOX client: {created_id}")
        return created_id
        
    except Exception as e:
        print(f"❌ Client fetch/create failed: {e}")
        return None

def check_schema_exists(token, client_id, schema_name):
    """
    Check if a schema with given name already exists in DOX
    
    Schemas in DOX define the structure of documents to extract.
    Before creating a new schema, we check if one with the same name
    already exists to avoid duplicates.
    
    Args:
        token (str): OAuth access token
        client_id (str): DOX client ID
        schema_name (str): Name of schema to look for
        
    Returns:
        dict: Schema object if found, None if not found
    """
    try:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DOX_BASE_URL}/schemas"
        params = {"clientId": client_id}
        
        # Get all schemas for this client
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            return None
            
        schemas = resp.json().get("schemas", [])
        
        # Search for schema by name
        for schema in schemas:
            if schema.get("name") == schema_name:
                print(f"✔️ Schema '{schema_name}' exists with ID: {schema['id']}")
                return schema
        
        print(f"📝 Schema '{schema_name}' not found")
        return None
        
    except Exception as e:
        print(f"❌ Error checking schema: {e}")
        return None

def import_schema(token, client_id, schema_name, schema_file_path):
    """
    Import a schema definition from JSON file into DOX
    
    This uploads our predefined schema (which fields to extract, their types,
    validation rules, etc.) to the DOX service.
    
    Args:
        token (str): OAuth access token
        client_id (str): DOX client ID
        schema_name (str): Name for the schema
        schema_file_path (Path): Path to schema JSON file
        
    Returns:
        bool: True if import successful, False otherwise
    """
    try:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DOX_BASE_URL}/schemas/import"
        params = {
            "clientId": client_id,
            "name": schema_name
        }
        
        # Upload schema file
        with open(schema_file_path, 'rb') as f:
            files = {'file': (schema_file_path.name, f, 'application/json')}
            resp = requests.post(url, headers=headers, params=params, files=files, timeout=30)
        
        success = resp.status_code in (200, 201)
        if success:
            print(f"✔️ Schema imported: {schema_name}")
        else:
            print(f"❌ Schema import failed: {resp.status_code}")
            
        return success
        
    except Exception as e:
        print(f"❌ Error importing schema: {e}")
        return False

def activate_schema_version(token, client_id, schema_id, version):
    """
    Activate a specific version of a schema
    
    In DOX, schemas can have multiple versions. Only one version can be
    active at a time. The active version is used for document processing.
    
    Args:
        token (str): OAuth access token
        client_id (str): DOX client ID
        schema_id (str): Schema ID
        version (str): Version number to activate (e.g., "1")
        
    Returns:
        bool: True if activation successful, False otherwise
    """
    try:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DOX_BASE_URL}/schemas/{schema_id}/versions/{version}/activate"
        params = {"clientId": client_id}
        
        resp = requests.post(url, headers=headers, params=params, timeout=30)
        success = resp.status_code in (200, 201)
        
        if success:
            print(f"✔️ Schema version {version} activated")
        else:
            print(f"⚠️ Schema activation returned: {resp.status_code}")
            
        return success
        
    except Exception as e:
        print(f"❌ Error activating schema: {e}")
        return False

def ensure_schema_exists(token, client_id, job=None):
    """
    Ensure the document schema exists in DOX, creating/importing if needed
    
    This is a key setup function that runs before document processing.
    It ensures the schema is available in DOX so documents can be processed.
    
    Flow:
        1. Check local cache for schema ID
        2. If not cached, query DOX for existing schema
        3. If not in DOX, import from local JSON file
        4. Activate the schema version
        5. Cache the schema ID
    
    Args:
        token (str): OAuth access token
        client_id (str): DOX client ID
        job (ProcessingJob, optional): Job object for logging
        
    Returns:
        str: Schema ID if successful, None if failed
    """
    schema_name = SCHEMA_DATA.get("name", "uae_noc_schema_custom_runtime_v2")
    
    # Step 1: Check cache
    if SCHEMA_FILE.exists():
        cached = json.loads(SCHEMA_FILE.read_text())
        if cached.get("schemaName") == schema_name:
            if job:
                job.add_log(f"✔️ Using cached schema: {cached['schemaId']}")
            return cached["schemaId"]
    
    # Step 2: Check if schema exists in DOX
    existing_schema = check_schema_exists(token, client_id, schema_name)
    if existing_schema:
        schema_id = existing_schema.get("id")
        # Cache it for next time
        SCHEMA_FILE.write_text(json.dumps({"schemaId": schema_id, "schemaName": schema_name}, indent=2))
        if job:
            job.add_log(f"✔️ Schema exists: {schema_id}")
        return schema_id
    
    # Step 3: Schema doesn't exist, need to import it
    if not SCHEMA_FILE_PATH:
        if job:
            job.add_log("❌ No local schema file found")
        return None
    
    if job:
        job.add_log(f"📦 Importing schema '{schema_name}'...")
    
    # Import the schema from JSON file
    import_success = import_schema(token, client_id, schema_name, SCHEMA_FILE_PATH)
    if not import_success:
        return None
    
    # After import, get the schema details
    new_schema = check_schema_exists(token, client_id, schema_name)
    if not new_schema:
        return None
    
    schema_id = new_schema.get("id")
    
    # Step 4: Activate the first version
    activate_schema_version(token, client_id, schema_id, "1")
    
    # Step 5: Cache the schema ID
    SCHEMA_FILE.write_text(json.dumps({"schemaId": schema_id, "schemaName": schema_name}, indent=2))
    
    if job:
        job.add_log(f"✔️ Schema imported and activated: {schema_id}")
    
    return schema_id

def upload_to_dox(file_bytes, filename, job=None):
    """
    Upload document to SAP DOX and retrieve extracted data
    
    This is the core function that:
        1. Authenticates with SAP UAA
        2. Gets/creates a DOX client
        3. Ensures schema exists
        4. Uploads the PDF file
        5. Polls for processing completion
        6. Retrieves extraction results
    
    Args:
        file_bytes (bytes): PDF file content as bytes
        filename (str): Original filename
        job (ProcessingJob, optional): Job object for logging
        
    Returns:
        tuple: (result_dict, http_status_code)
            - result_dict: Extraction results or error message
            - http_status_code: HTTP status code (200 for success)
    """
    # Validation: Ensure DOX is configured
    if not config_valid:
        if job:
            job.add_log("❌ SAP DOX not configured")
        return {"error": "SAP DOX not configured"}, 500
    
    # Step 1: Get authentication token
    token = get_token()
    if not token:
        if job:
            job.add_log("❌ Token retrieval failed")
        return {"error": "Token retrieval failed"}, 500

    # Step 2: Get DOX client ID
    client_id = get_or_create_client(token)
    if not client_id:
        if job:
            job.add_log("❌ Client ID retrieval failed")
        return {"error": "Client ID retrieval failed"}, 500

    # Step 3: Ensure schema is available
    if job:
        job.add_log("🔍 Checking schema...")
    schema_id = ensure_schema_exists(token, client_id, job)
    
    # Prepare upload request
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": (filename, file_bytes, "application/pdf")}
    
    schema_name = SCHEMA_DATA.get("name", "uae_noc_schema_custom_runtime_v2")
    
    # Document processing options
    options = {
        "clientId": client_id,
        "documentType": "custom",  # Using custom schema, not predefined
        "receivedDate": datetime.utcnow().strftime("%Y-%m-%d")
    }
    
    # Use schemaId if available, otherwise use schemaName
    # (DOX API accepts only one, schemaId takes precedence)
    if schema_id:
        options["schemaId"] = schema_id
    else:
        options["schemaName"] = schema_name
        
    data = {"options": json.dumps(options)}

    if job:
        job.add_log(f"⏳ Uploading '{filename}' to SAP DOX...")
    
    # Step 4: Upload document for processing
    resp = requests.post(
        f"{DOX_BASE_URL}/document/jobs",
        headers=headers,
        files=files,
        data=data,
        timeout=120  # 2 minute timeout for upload
    )
    
    # Handle upload errors
    if resp.status_code >= 400:
        if job:
            job.add_log(f"❌ Upload failed: {resp.status_code}")
        return {"error": resp.text}, resp.status_code

    # Extract job ID from response
    job_id = resp.json().get("id")
    if not job_id:
        return {"error": "Job ID missing"}, 500

    if job:
        job.add_log(f"✔️ Upload successful — Job ID: {job_id}")

    # Step 5: Poll for completion
    # DOX processes documents asynchronously, so we need to poll the status
    max_attempts = CONFIG.get("max_poll_attempts", 60)  # Default: 60 attempts
    poll_interval = CONFIG.get("poll_interval", 2)      # Default: 2 seconds
    
    for attempt in range(max_attempts):
        time.sleep(poll_interval)  # Wait before checking status
        
        # Query job status
        poll = requests.get(
            f"{DOX_BASE_URL}/document/jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30
        )
        
        if poll.status_code != 200:
            continue  # Retry on error
            
        status = poll.json().get("status", "").upper()
        
        # Check if processing is complete
        if status == "DONE":
            if job:
                job.add_log("✔️ Processing complete")
            break  # Exit polling loop
            
        # Check if processing failed
        if status in ("FAILED", "ERROR"):
            if job:
                job.add_log("❌ Processing failed")
            return {"error": "Processing failed", "details": poll.json()}, 500
            
        # Log progress every 5 attempts (every 10 seconds)
        if job and attempt % 5 == 0:
            job.add_log(f"⏳ Polling... ({attempt+1}/{max_attempts})")
    else:
        # Loop completed without break (timeout)
        return {"error": "Timeout waiting for completion"}, 504

    # Step 6: Fetch extraction results
    fetch_url = f"{DOX_BASE_URL}/document/jobs/{job_id}"
    res = requests.get(
        fetch_url,
        headers=headers,
        params={"extractedValues": "true"},  # Include extracted field values
        timeout=60
    )
    
    if res.status_code != 200:
        return {"error": res.text}, res.status_code

    if job:
        job.add_log("✔️ Extraction fetched successfully")
        
    return res.json(), 200

# ═══════════════════════════════════════════════════════════════════════════
# CONFIDENCE COMPUTATION - WEIGHTED SCORING SYSTEM
# ═══════════════════════════════════════════════════════════════════════════
# This is the core algorithm that determines document validity based on
# AI extraction confidence scores.

def compute_confidence(fields, use_approximation=False):
    """
    Compute overall confidence score using weighted field contributions
    
    ╔════════════════════════════════════════════════════════════════════════╗
    ║ WEIGHTS CONFIGURATION - HOW TO MODIFY                                 ║
    ╠════════════════════════════════════════════════════════════════════════╣
    ║                                                                        ║
    ║ The confidence score is calculated as a weighted sum of individual    ║
    ║ field confidence scores. Each field has:                              ║
    ║                                                                        ║
    ║   1. CONFIDENCE (0.0 to 1.0): AI's certainty in extraction           ║
    ║   2. WEIGHT (0.0 to 1.0): Importance of this field                   ║
    ║   3. CONTRIBUTION: confidence × weight                                ║
    ║                                                                        ║
    ║ Example: If applicationNumber has confidence=0.9 and weight=0.2,      ║
    ║          its contribution is 0.9 × 0.2 = 0.18 (18%)                  ║
    ║                                                                        ║
    ╠════════════════════════════════════════════════════════════════════════╣
    ║ TO CHANGE WEIGHTS:                                                     ║
    ╠════════════════════════════════════════════════════════════════════════╣
    ║                                                                        ║
    ║ Option 1: Edit config.json (Recommended)                              ║
    ║ ────────────────────────────────                                      ║
    ║ Add or modify the "field_weights" section:                            ║
    ║                                                                        ║
    ║   {                                                                    ║
    ║     "field_weights": {                                                 ║
    ║       "applicationNumber": 0.3,  ← 30% importance                     ║
    ║       "issuingAuthority": 0.25,  ← 25% importance                     ║
    ║       "ownerName": 0.2,          ← 20% importance                     ║
    ║       "issueDate": 0.15,         ← 15% importance                     ║
    ║       "documentStatus": 0.1      ← 10% importance                     ║
    ║     }                                                                  ║
    ║   }                                                                    ║
    ║                                                                        ║
    ║   ⚠️ IMPORTANT: All weights must sum to 1.0 (100%)                    ║
    ║                                                                        ║
    ║ Option 2: Modify code below (For testing only)                        ║
    ║ ──────────────────────────────────────────                            ║
    ║ Change the default values in the weighted_subset dictionary           ║
    ║                                                                        ║
    ╠════════════════════════════════════════════════════════════════════════╣
    ║ WEIGHT DESIGN PRINCIPLES:                                              ║
    ╠════════════════════════════════════════════════════════════════════════╣
    ║                                                                        ║
    ║ 1. Critical Fields (0.20-0.30):                                        ║
    ║    - Fields that uniquely identify the document                        ║
    ║    - Example: applicationNumber (the NOC reference ID)                 ║
    ║                                                                        ║
    ║ 2. Important Fields (0.15-0.25):                                       ║
    ║    - Fields needed for validation and legal purposes                   ║
    ║    - Example: issuingAuthority, ownerName                              ║
    ║                                                                        ║
    ║ 3. Supporting Fields (0.05-0.15):                                      ║
    ║    - Fields that provide context but aren't critical                   ║
    ║    - Example: issueDate, documentStatus                                ║
    ║                                                                        ║
    ║ 4. Non-Weighted Fields (0.0):                                          ║
    ║    - Extracted for information but don't affect score                  ║
    ║    - Example: expiryDate, remarks (if not mandatory)                   ║
    ║                                                                        ║
    ║ 5. Non-Weighted Fields (0.0):                                          ║
    ║    - Extracted for information but don't affect score                  ║
    ║    - Example: expiryDate, remarks (if not mandatory)                   ║
    ║                                                                        ║
    ╠════════════════════════════════════════════════════════════════════════╣
    ║ SCORING EXAMPLE:                                                       ║
    ╠════════════════════════════════════════════════════════════════════════╣
    ║                                                                        ║
    ║ Field              | Confidence | Weight | Contribution               ║
    ║ ──────────────────────────────────────────────────────────────────    ║
    ║ applicationNumber  |   95%      | 0.30   | 0.95 × 0.30 = 0.285       ║
    ║ issuingAuthority   |   90%      | 0.25   | 0.90 × 0.25 = 0.225       ║
    ║ ownerName          |   85%      | 0.20   | 0.85 × 0.20 = 0.170       ║
    ║ issueDate          |   80%      | 0.15   | 0.80 × 0.15 = 0.120       ║
    ║ documentStatus     |   70%      | 0.10   | 0.70 × 0.10 = 0.070       ║
    ║                                            ──────────────────         ║
    ║                                  TOTAL:   0.870 = 87% confidence      ║
    ║                                                                        ║
    ╚════════════════════════════════════════════════════════════════════════╝
    
    Args:
        fields (dict): Extracted fields from DOX with confidence scores
                      Format: {field_name: {value: "...", confidence: 0.9}}
        use_approximation (bool): If True, use simplified mandatory-field logic
        
    Returns:
        tuple: (total_confidence, breakdown)
            - total_confidence (float): Overall score (0.0 to 1.0)
            - breakdown (list): Detailed per-field analysis
    """
    
    # ═══════════════════════════════════════════════════════════════════════
    # LOAD FIELD WEIGHTS FROM CONFIG OR USE DEFAULTS
    # ═══════════════════════════════════════════════════════════════════════
    # This is where you can change the importance of each field!
    # The weights determine how much each field contributes to the final score.
    
    weighted_subset = CONFIG.get("field_weights", {
        # DEFAULT WEIGHTS (if not in config.json)
        # ───────────────────────────────────────────────────────────────
        "applicationNumber": 0.2,   # 20% - NOC reference number (Critical)
        "issuingAuthority": 0.2,    # 20% - Government authority (Critical)
        "ownerName": 0.2,           # 20% - Person/company name (Critical)
        "issueDate": 0.2,           # 20% - When NOC was issued (Important)
        "documentStatus": 0.2       # 20% - Approval status (Important)
        # ───────────────────────────────────────────────────────────────
        # TOTAL MUST = 1.0 (100%)
        # ───────────────────────────────────────────────────────────────
    })
    
    # ⚠️ VALIDATION: Check that weights sum to 1.0
    total_weight = sum(weighted_subset.values())
    if abs(total_weight - 1.0) > 0.001:  # Allow small floating-point errors
        print(f"⚠️ WARNING: Field weights sum to {total_weight}, not 1.0!")
        print("   This will affect confidence scores. Please fix config.json")

    # Initialize accumulators
    total_conf = 0.0  # Sum of all weighted contributions
    breakdown = []    # Detailed per-field analysis for UI display

    # ═══════════════════════════════════════════════════════════════════════
    # PROCESS EACH FIELD
    # ═══════════════════════════════════════════════════════════════════════
    for k in ALL_FIELDS:
        # Get field information from extraction results
        info = fields.get(k, {})
        
        # Extract confidence score (AI's certainty: 0.0 = no confidence, 1.0 = 100% sure)
        raw_conf = info.get("confidence") if isinstance(info, dict) else 0
        conf = float(raw_conf) if isinstance(raw_conf, (int, float)) else 0.0
        
        # Get extracted value (the actual text found in the document)
        val = info.get("value") or "—"  # Use "—" if no value found

        # Get weight for this field (0.0 if not in weighted_subset)
        weight = weighted_subset.get(k, 0.0)
        
        # Calculate contribution: confidence × weight
        # This is how much this field contributes to the final score
        contrib = conf * weight
        
        # Only add to total if field is weighted (has importance > 0)
        if k in weighted_subset:
            total_conf += contrib

        # ───────────────────────────────────────────────────────────────────
        # Visual Classification for UI Display
        # ───────────────────────────────────────────────────────────────────
        if k in weighted_subset:
            row_color = "#e6ffe6"  # Light green - This field affects score
        else:
            row_color = "#f7f7f7"  # Light grey - Informational only

        # Build detailed breakdown row for this field
        breakdown.append({
            "Field": FRIENDLY_LABELS.get(k, k),  # User-friendly name
            "Name": k,                            # Technical field name
            "Extracted Value": val,               # What was found in document
            "Confidence (%)": round(conf * 100, 1),     # AI confidence as percentage
            "Weight (%)": round(weight * 100, 1),       # Field importance as percentage
            "Contribution (%)": round(contrib * 100, 1), # Actual contribution to score
            "Row Color": row_color                # For UI styling
        })

    # ═══════════════════════════════════════════════════════════════════════
    # APPROXIMATION LOGIC (OPTIONAL)
    # ═══════════════════════════════════════════════════════════════════════
    # When enabled, uses simplified logic based on mandatory fields only:
    #   - If ALL mandatory fields present with ≥70% confidence → 100% score
    #   - If ANY mandatory field missing → 0% score
    #   - Otherwise → Use weighted calculation above
    
    if use_approximation:
        # Check if all mandatory fields are present
        mandatory_present = all(fields.get(f) for f in MANDATORY_FIELDS)
        
        # Check if all mandatory fields have high confidence (≥70%)
        mandatory_high_conf = all(
            (fields.get(f, {}).get("confidence", 0) or 0) >= 0.7 
            for f in MANDATORY_FIELDS
        )
        
        if mandatory_present and mandatory_high_conf:
            print("✔️ Approximation: All mandatory fields ≥70% → 100% confidence")
            total_conf = 1.0
        elif not mandatory_present:
            print("❌ Approximation: Missing mandatory fields → 0% confidence")
            total_conf = 0.0
        # If mandatory present but low confidence, keep weighted calculation

    # Ensure final score is between 0.0 and 1.0
    total_conf = min(round(total_conf, 3), 1.0)
    
    return total_conf, breakdown

# ═══════════════════════════════════════════════════════════════════════════
# BUSINESS RULE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════
# Additional validation layer to check extracted values against business rules

def validate_business_rules(fields, job=None):
    """
    Validate extracted fields against configurable business rules
    
    This function performs post-extraction validation to ensure documents
    meet business requirements beyond just AI confidence scores.
    
    Supported Rule Types:
        1. date_age: Check if date is within specified age limit
           - Example: Issue date must be ≤ 6 months old
        
        2. whitelist: Check if value is in approved list
           - Example: Authority must be from government entity list
        
        3. regex: Check if value matches a pattern (future enhancement)
        
        4. range: Check if numeric value is within range (future enhancement)
    
    Args:
        fields (dict): Extracted fields from DOX
        job (ProcessingJob, optional): Job object for logging
        
    Returns:
        dict: {
            "valid": bool - True if all rules passed
            "violations": list - Critical rule violations
            "warnings": list - Non-critical issues
            "validation_details": dict - Per-field validation results
        }
    """
    # Load validation rules from config
    validation_rules = CONFIG.get("validation_rules", {})
    
    # If no rules configured, skip validation
    if not validation_rules:
        return {
            "valid": True,
            "violations": [],
            "warnings": [],
            "validation_details": {},
            "fields_validated": 0  # Track that no validation occurred
        }
    
    violations = []  # Critical errors (will downgrade status)
    warnings = []    # Non-critical issues (informational)
    validation_details = {}
    fields_validated = 0  # Counter for fields actually validated
    
    # Process each validation rule
    for field_name, rule in validation_rules.items():
        field_data = fields.get(field_name, {})
        value = field_data.get("value")
        
        # Skip validation if field not extracted
        if not value:
            warnings.append(f"⚠️ Field '{field_name}' not extracted - cannot validate")
            validation_details[field_name] = {
                "status": "skipped",
                "reason": "Field not extracted"
            }
            continue
        
        # ───────────────────────────────────────────────────────────────────
        # DATE AGE VALIDATION
        # ───────────────────────────────────────────────────────────────────
        # Check if a date field is within allowed age limit
        if rule.get("type") == "date_age":
            try:
                from dateutil import parser as date_parser
                
                # Parse date (handles multiple formats: DD/MM/YYYY, YYYY-MM-DD, etc.)
                date_value = date_parser.parse(value)
                
                # Calculate age in months
                age_days = (datetime.now() - date_value).days
                age_months = age_days / 30.44  # Average days per month
                
                max_age = rule.get("max_age_months", 6)
                
                if age_months > max_age:
                    # Date too old - violation
                    violations.append(
                        f"❌ {FRIENDLY_LABELS.get(field_name, field_name)}: "
                        f"Date is {age_months:.1f} months old (exceeds {max_age} month limit). "
                        f"{rule.get('error_message', '')}"
                    )
                    validation_details[field_name] = {
                        "status": "failed",
                        "value": value,
                        "parsed_date": date_value.strftime("%Y-%m-%d"),
                        "age_months": round(age_months, 1),
                        "max_allowed_months": max_age,
                        "error": rule.get('error_message', '')
                    }
                    if job:
                        job.add_log(f"❌ Date validation failed: {field_name} is {age_months:.1f} months old")
                else:
                    # Date within limit - pass
                    validation_details[field_name] = {
                        "status": "passed",
                        "value": value,
                        "parsed_date": date_value.strftime("%Y-%m-%d"),
                        "age_months": round(age_months, 1),
                        "max_allowed_months": max_age
                    }
                    fields_validated += 1  # Increment counter
                    if job:
                        job.add_log(f"✔️ Date validation passed: {field_name} is {age_months:.1f} months old")
                        
            except Exception as e:
                # Could not parse date
                warnings.append(
                    f"⚠️ {FRIENDLY_LABELS.get(field_name, field_name)}: "
                    f"Could not parse date '{value}': {str(e)}"
                )
                validation_details[field_name] = {
                    "status": "error",
                    "value": value,
                    "error": f"Date parsing failed: {str(e)}"
                }
                if job:
                    job.add_log(f"⚠️ Date parsing error for {field_name}: {e}")
        
        # ───────────────────────────────────────────────────────────────────
        # WHITELIST VALIDATION
        # ───────────────────────────────────────────────────────────────────
        # Check if value is in approved list
        elif rule.get("type") == "whitelist":
            allowed_values = rule.get("allowed_values", [])
            case_sensitive = rule.get("case_sensitive", False)
            fuzzy_match = rule.get("fuzzy_match", False)
            
            is_valid = False
            matched_value = None
            
            # Exact matching
            if case_sensitive:
                is_valid = value in allowed_values
                matched_value = value if is_valid else None
            else:
                # Case-insensitive matching
                value_lower = value.lower().strip()
                for allowed in allowed_values:
                    if value_lower == allowed.lower().strip():
                        is_valid = True
                        matched_value = allowed
                        break
            
            # Fuzzy matching (partial match)
            if not is_valid and fuzzy_match:
                value_lower = value.lower().strip()
                # Split both values into words for better matching
                value_words = set(value_lower.split())
                
                for allowed in allowed_values:
                    allowed_lower = allowed.lower().strip()
                    allowed_words = set(allowed_lower.split())
                    
                    # Check if either contains the other (original logic)
                    if value_lower in allowed_lower or allowed_lower in value_lower:
                        is_valid = True
                        matched_value = allowed
                        if job:
                            job.add_log(f"ℹ️ Fuzzy match (substring): '{value}' ≈ '{allowed}'")
                        break
                    
                    # Check if significant word overlap (at least 2 common words)
                    common_words = value_words & allowed_words
                    # Filter out common words like "municipality", "city", etc. for better matching
                    significant_words = {w for w in common_words if len(w) > 3}
                    
                    if len(significant_words) >= 2:
                        is_valid = True
                        matched_value = allowed
                        if job:
                            job.add_log(f"ℹ️ Fuzzy match (word overlap): '{value}' ≈ '{allowed}' (matched: {', '.join(significant_words)})")
                        break
            
            if not is_valid:
                # Value not in whitelist - violation
                violations.append(
                    f"❌ {FRIENDLY_LABELS.get(field_name, field_name)}: "
                    f"Value '{value}' not in approved list. "
                    f"{rule.get('error_message', '')}"
                )
                validation_details[field_name] = {
                    "status": "failed",
                    "value": value,
                    "allowed_values": allowed_values,
                    "error": rule.get('error_message', '')
                }
                if job:
                    job.add_log(f"❌ Whitelist validation failed: '{value}' not approved")
            else:
                # Value is approved
                validation_details[field_name] = {
                    "status": "passed",
                    "value": value,
                    "matched_value": matched_value
                }
                fields_validated += 1  # Increment counter
                if job:
                    job.add_log(f"✔️ Whitelist validation passed: '{value}' is approved")
    
    # Determine overall validation status
    is_valid = len(violations) == 0
    
    return {
        "valid": is_valid,
        "violations": violations,
        "warnings": warnings,
        "validation_details": validation_details,
        "fields_validated": fields_validated  # Include count of validated fields
    }

# ═══════════════════════════════════════════════════════════════════════════
# ASYNC DOCUMENT PROCESSING WORKER
# ═══════════════════════════════════════════════════════════════════════════
# This function runs in a background thread to process documents without
# blocking the web server.

def upload_chunk_worker(chunk_data):
    """
    Worker function for parallel chunk processing
    
    This function is executed in a separate thread for each chunk,
    enabling parallel uploads to SAP DOX AI.
    
    Args:
        chunk_data (tuple): (chunk_index, chunk_bytes, filename_suffix, job, total_chunks)
        
    Returns:
        tuple: (chunk_index, result, status_code)
    """
    chunk_index, chunk_bytes, filename_suffix, job, total_chunks = chunk_data
    
    try:
        # Upload chunk to SAP DOX
        result, code = upload_to_dox(chunk_bytes, filename_suffix, job)
        
        # Thread-safe progress update
        # Calculate progress contribution for this chunk
        with progress_lock:
            # Ensure we don't exceed 70% during chunk processing
            current_progress = 20 + int(((chunk_index + 1) / total_chunks) * 50)
            if current_progress > job.progress:
                job.progress = min(current_progress, 70)
        
        return (chunk_index, result, code)
        
    except Exception as e:
        # Worker exception - return error status
        import traceback
        error_trace = traceback.format_exc()
        job.add_log(f"❌ Worker exception for chunk {chunk_index + 1}: {e}")
        job.add_log(f"Traceback: {error_trace}")
        return (chunk_index, {"error": str(e)}, 500)


def process_document_async(job_id, file_bytes, filename, use_approx, use_validation=False):
    """
    Background worker that processes a document asynchronously
    
    This runs in a separate thread so the web server remains responsive
    while documents are being processed by SAP DOX AI.
    
    Processing Steps:
        1. Update job status to "processing"
        2. Check PDF page count
        3. Split PDF into chunks if needed (large documents)
        4. Upload chunks to SAP DOX AI IN PARALLEL (NEW!)
        5. Combine results from all chunks
        6. Calculate confidence score
        7. Run business rule validation (if enabled)
        8. Determine approval status
        9. Store results in job object
    
    Args:
        job_id (str): Unique job identifier
        file_bytes (bytes): PDF file content
        filename (str): Original filename
        use_approx (bool): Whether to use approximation logic
        use_validation (bool): Whether to run business rule validation
    """
    
    # Get job object (thread-safe access with lock)
    with job_lock:
        job = processing_jobs.get(job_id)
        if not job:
            return  # Job was cancelled or doesn't exist
        job.status = "processing"
        job.progress = 10  # 10% progress
    
    try:
        job.add_log("🌀 Starting document processing...")
        
        # ───────────────────────────────────────────────────────────────────
        # STEP 1: PDF ANALYSIS AND CHUNKING
        # ───────────────────────────────────────────────────────────────────
        # Large PDFs can exceed DOX processing limits, so we split them
        # into smaller chunks and process separately.
        
        max_pages_per_chunk = CONFIG.get("max_pages_per_chunk", 10)
        pdf_reader = PyPDF2.PdfReader(BytesIO(file_bytes))
        num_pages = len(pdf_reader.pages)
        
        job.add_log(f"📄 PDF has {num_pages} pages")
        
        # ───────────────────────────────────────────────────────────────────
        # CAPTURE FIRST 10 PAGES AS THUMBNAILS
        # ───────────────────────────────────────────────────────────────────
        thumbnails_base64 = []
        file_size_mb = len(file_bytes) / (1024 * 1024)
        start_time = time.time()
        
        try:
            job.add_log("📸 Generating document previews...")
            
            # Open PDF with PyMuPDF
            pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # Determine how many pages to capture (max 10, or fewer if document is shorter)
            pages_to_capture = min(10, num_pages)
            
            # Extract first N pages as images
            for page_num in range(pages_to_capture):
                page = pdf_doc[page_num]
                
                # Render at 150 DPI for good quality (balance between size and clarity)
                pix = page.get_pixmap(dpi=150)
                
                # Convert to PNG bytes
                img_bytes = pix.tobytes("png")
                
                # Encode as base64 for embedding in HTML
                thumbnail_b64 = base64.b64encode(img_bytes).decode('utf-8')
                thumbnails_base64.append(thumbnail_b64)
            
            pdf_doc.close()
            total_size = sum(len(base64.b64decode(t)) for t in thumbnails_base64) / 1024
            job.add_log(f"✔️ {len(thumbnails_base64)} preview(s) captured ({total_size:.1f} KB total)")
            
        except Exception as e:
            job.add_log(f"⚠️ Could not generate previews: {e}")
            # Continue processing even if preview fails
        
        job.progress = 20  # 20% progress
        
        if num_pages > max_pages_per_chunk:
            # Document is too large, split into chunks
            job.add_log(f"📄 Splitting into chunks of {max_pages_per_chunk} pages...")
            chunks = []
            
            # Create chunks by splitting pages
            for i in range(0, num_pages, max_pages_per_chunk):
                pdf_writer = PyPDF2.PdfWriter()
                
                # Add pages to this chunk
                for j in range(i, min(i + max_pages_per_chunk, num_pages)):
                    pdf_writer.add_page(pdf_reader.pages[j])
                
                # Write chunk to memory
                output = BytesIO()
                pdf_writer.write(output)
                chunks.append(output.getvalue())
                
            job.add_log(f"📄 Split into {len(chunks)} chunks")
        else:
            # Document is small enough, process as single chunk
            chunks = [file_bytes]
        
        # ───────────────────────────────────────────────────────────────────
        # STEP 2: PROCESS CHUNKS IN PARALLEL (NEW!)
        # ───────────────────────────────────────────────────────────────────
        # For multiple chunks, process them concurrently to reduce total time.
        # Configuration allows tuning parallelism to avoid overwhelming API.
        
        total_chunks = len(chunks)
        all_results = []  # Store results from all chunks
        
        # Determine processing mode based on number of chunks
        if total_chunks == 1:
            # Single chunk - use sequential processing (no overhead)
            job.add_log(f"📤 Processing single chunk...")
            result, code = upload_to_dox(chunks[0], f"{filename}_chunk_1", job)
            
            if code != 200:
                job.status = "failed"
                job.error = f"Upload failed: {result}"
                job.add_log(f"❌ {job.error}")
                return
            
            all_results.append(result)
            job.progress = 70  # 70% progress after chunk processing
            
        else:
            # Multiple chunks - use parallel processing
            max_workers = min(total_chunks, CONFIG.get("max_parallel_chunks", 3))
            job.add_log(f"🔄 Processing {total_chunks} chunks in parallel (max {max_workers} concurrent)...")
            
            # Prepare chunk data for workers
            chunk_data_list = [
                (i, chunk, f"{filename}_chunk_{i+1}", job, total_chunks)
                for i, chunk in enumerate(chunks)
            ]
            
            # Dictionary to store results by chunk index (thread-safe)
            results_dict = {}
            results_lock = threading.Lock()
            
            # Process chunks in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all chunk processing tasks
                future_to_index = {
                    executor.submit(upload_chunk_worker, data): data[0]
                    for data in chunk_data_list
                }
                
                # Monitor completion and handle results
                for future in as_completed(future_to_index):
                    chunk_idx = future_to_index[future]
                    
                    try:
                        # Get result from completed worker
                        idx, result, code = future.result()
                        
                        # Check for errors
                        if code != 200:
                            # Chunk failed - cancel all pending tasks (fail-fast)
                            job.add_log(f"❌ Chunk {idx + 1} failed with code {code}")
                            
                            # Cancel all pending futures
                            for f in future_to_index:
                                if not f.done():
                                    f.cancel()
                            
                            # Mark job as failed
                            job.status = "failed"
                            job.error = f"Upload failed for chunk {idx + 1}: {result}"
                            job.add_log(f"❌ {job.error}")
                            
                            # Shutdown executor and return
                            executor.shutdown(wait=False)
                            return
                        
                        # Success - store result (thread-safe)
                        with results_lock:
                            results_dict[idx] = result
                            job.add_log(f"✔️ Chunk {idx + 1}/{total_chunks} completed successfully")
                        
                    except Exception as e:
                        # Worker raised an exception
                        import traceback
                        error_trace = traceback.format_exc()
                        job.add_log(f"❌ Exception processing chunk {chunk_idx + 1}: {e}")
                        job.add_log(f"Traceback: {error_trace}")
                        
                        # Cancel remaining tasks
                        for f in future_to_index:
                            if not f.done():
                                f.cancel()
                        
                        job.status = "failed"
                        job.error = f"Exception in chunk {chunk_idx + 1}: {e}"
                        executor.shutdown(wait=False)
                        return
            
            # All chunks completed successfully - sort results by index
            all_results = [results_dict[i] for i in range(total_chunks)]
            job.progress = 70  # 70% progress after all chunks processed
            job.add_log(f"✔️ All {total_chunks} chunks processed successfully")
        
        job.progress = 75  # 75% progress - chunks processed
        job.add_log("🔄 Combining results from all chunks...")
        
        # ───────────────────────────────────────────────────────────────────
        # STEP 3: COMBINE RESULTS FROM ALL CHUNKS
        # ───────────────────────────────────────────────────────────────────
        # When a document is split into chunks, we need to merge the
        # extraction results. Strategy: For each field, keep the value
        # with the highest confidence.
        
        combined_extraction = {}
        
        for result in all_results:
            # Navigate through DOX response structure
            extraction = result.get("extraction", {}) if isinstance(result, dict) else {}
            header_fields = extraction.get("headerFields", [])
            
            for field in header_fields:
                name = field.get("name")
                
                # If field not seen yet, or this value has higher confidence, use it
                if (name not in combined_extraction or 
                    field.get("confidence", 0) > combined_extraction[name].get("confidence", 0)):
                    combined_extraction[name] = field
        
        fields = combined_extraction
        
        # ───────────────────────────────────────────────────────────────────
        # STEP 4: CALCULATE CONFIDENCE SCORE
        # ───────────────────────────────────────────────────────────────────
        job.add_log("📊 Computing confidence scores...")
        conf, breakdown = compute_confidence(fields, use_approximation=use_approx)
        
        # ───────────────────────────────────────────────────────────────────
        # STEP 5: BUSINESS RULE VALIDATION (IF ENABLED)
        # ───────────────────────────────────────────────────────────────────
        validation_result = None
        if use_validation:
            job.add_log("🔍 Running business rule validation...")
            job.progress = 80  # 80% progress
            
            validation_result = validate_business_rules(fields, job)
            
            if validation_result["valid"]:
                job.add_log("✔️ All business rules passed")
            else:
                job.add_log(f"⚠️ {len(validation_result['violations'])} validation rule(s) failed")
                for violation in validation_result["violations"]:
                    job.add_log(f"   {violation}")
        
        # ───────────────────────────────────────────────────────────────────
        # STEP 6: DETERMINE DOCUMENT STATUS
        # ───────────────────────────────────────────────────────────────────
        # Status determination considers both confidence AND validation results
        
        # Load thresholds from config (can be customized)
        approval_threshold = CONFIG.get("approval_threshold", 0.85)  # 85%
        review_threshold = CONFIG.get("review_threshold", 0.6)       # 60%
        
        # Initial classification based on confidence
        if conf >= approval_threshold:
            status = "Approved"
        elif conf >= review_threshold:
            status = "Needs Review"
        else:
            status = "Rejected"
        
        # Downgrade status if validation failed
        if use_validation and validation_result and not validation_result["valid"]:
            if status == "Approved":
                # Downgrade Approved to Needs Review if validation fails
                status = "Needs Review"
                job.add_log("⚠️ Status downgraded to 'Needs Review' due to validation failures")
            # Rejected stays Rejected (no further downgrade needed)
        
        job.progress = 90  # 90% progress
        job.add_log(f"✔️ Final Status: {status} ({conf*100:.1f}% confidence)")
        
        # ───────────────────────────────────────────────────────────────────
        # STEP 7: STORE RESULTS IN JOB OBJECT
        # ───────────────────────────────────────────────────────────────────
        processing_time = time.time() - start_time
        
        job.result = {
            "filename": filename,
            "num_pages": num_pages,
            "file_size_mb": round(file_size_mb, 2),
            "processing_time": round(processing_time, 1),
            "thumbnails": thumbnails_base64,  # List of base64-encoded page images
            "confidence": conf,        # Overall confidence score (0.0-1.0)
            "status": status,          # Approved/Needs Review/Rejected
            "breakdown": breakdown,    # Detailed per-field analysis
            "fields": fields,          # Raw extracted fields
            "raw_results": all_results, # Complete DOX API responses
            "validation_result": validation_result  # Business rule validation results
        }
        
        # Mark job as completed successfully
        job.status = "completed"
        job.progress = 100  # 100% complete
        job.add_log("🎉 Processing completed successfully!")
        
    except Exception as e:
        # ───────────────────────────────────────────────────────────────────
        # ERROR HANDLING
        # ───────────────────────────────────────────────────────────────────
        import traceback
        error_trace = traceback.format_exc()
        
        # Mark job as failed and store error details
        job.status = "failed"
        job.error = str(e)
        job.add_log(f"❌ Exception: {e}")
        job.add_log(f"Traceback: {error_trace}")
        print(error_trace)  # Print full error to server console

# ═══════════════════════════════════════════════════════════════════════════
# FLASK WEB SERVER INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════
# Flask provides the web server that hosts both the dashboard and API

server = Flask(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# DASH INTERACTIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════
# Dash is built on top of Flask and provides reactive web components
# (similar to React.js but in Python)

dash_app = Dash(
    __name__, 
    server=server,                    # Use Flask server
    url_base_pathname="/dashboard/",  # Dashboard available at /dashboard/
    title="SAP NOC DOX AI",
    update_title="Processing...",     # Browser tab title during updates
    suppress_callback_exceptions=True # Prevent errors for dynamic components
)

# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD LAYOUT - USER INTERFACE STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════
# The layout defines the visual structure of the dashboard using HTML
# components provided by Dash.

dash_app.layout = html.Div([
    
    # ───────────────────────────────────────────────────────────────────────
    # HEADER SECTION
    # ───────────────────────────────────────────────────────────────────────
    html.Div([
        # SAP Logo
        html.Div([
            html.Img(src="/static/sap-logo.png", className="header-logo", alt="SAP Logo"),
        ], className="header-logo-container"),
        
        # App Title and Description
        html.Div([
            html.H1(CONFIG.get("app_name", "AI Validator"), className="header-title"),
            html.P(f"{CONFIG.get('description', 'AI-Powered Document Validation')} • v{APP_VERSION}", 
                   style={"fontSize": "0.875rem", "color": "rgba(255,255,255,0.8)", "marginTop": "0.25rem"}),
        ], className="header-content"),
        
        # Status badges (show connection status)
        html.Div([
            html.Span(id="config-status", className="status-badge"),
        ], className="header-badges")
    ], className="header"),
    
    # ───────────────────────────────────────────────────────────────────────
    # TAB NAVIGATION
    # ───────────────────────────────────────────────────────────────────────
    html.Div([
        html.Button([
            html.Span(className="sap-icon sap-icon--validate"),
            html.Span("Validator")
        ], id="tab-validator", className="tab-button active", n_clicks=0),
        html.Button([
            html.Span(className="sap-icon sap-icon--schema"),
            html.Span("Schema Config")
        ], id="tab-schema", className="tab-button", n_clicks=0),
        html.Button([
            html.Span(className="sap-icon sap-icon--rules"),
            html.Span("Business Rules")
        ], id="tab-rules", className="tab-button", n_clicks=0),
        html.Button([
            html.Span(className="sap-icon sap-icon--dashboard"),
            html.Span("Dashboard")
        ], id="tab-dashboard", className="tab-button", n_clicks=0),
    ], className="tab-navigation"),
    
    # Confirmation dialog (hidden by default)
    html.Div([
        html.Div([
            html.Div([
                html.Span(className="sap-icon sap-icon--warning sap-icon--lg", style={"color": "var(--sap-warning)", "marginRight": "10px"}),
                html.Span("Confirm Document Cleanup", style={"fontWeight": "700"})
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "1rem"}),
            html.P("This will permanently delete ALL documents from SAP DOX.", 
                   style={"marginBottom": "10px"}),
            html.P("This operation cannot be undone!", 
                   style={"fontWeight": "bold", "color": "#d11a2a", "marginBottom": "20px"}),
            html.Div([
                html.Button("Cancel", id="cleanup-cancel", className="dialog-button-cancel"),
                html.Button("Delete All Documents", id="cleanup-confirm", className="dialog-button-confirm"),
            ], style={"display": "flex", "gap": "10px", "justifyContent": "flex-end"})
        ], className="dialog-content")
    ], id="cleanup-dialog", className="dialog-overlay", style={"display": "none"}),
    
    # Cleanup status message
    dcc.Store(id="cleanup-trigger", data=0),
    
    # ═══════════════════════════════════════════════════════════════════════
    # TAB CONTENT: VALIDATOR (Main Processing View)
    # ═══════════════════════════════════════════════════════════════════════
    html.Div([
    # ───────────────────────────────────────────────────────────────────────
    # MAIN CONTENT AREA - TWO-COLUMN LAYOUT
    # ───────────────────────────────────────────────────────────────────────
    html.Div([
        
        # ═══════════════════════════════════════════════════════════════════
        # LEFT PANEL - UPLOAD & LOGS
        # ═══════════════════════════════════════════════════════════════════
        html.Div([
            
            # Upload Section
            html.Div([
                html.H3([
                    html.Span(className="sap-icon sap-icon--upload", style={"marginRight": "8px", "color": "var(--sap-brand-blue)"}),
                    "Document Upload"
                ], className="panel-title"),
                
                # File upload component (drag & drop or click to select)
                dcc.Upload(
                    id="upload-pdf",
                    children=html.Div([
                        html.I(className="upload-icon"),
                        html.P("Drag & Drop PDF here", className="upload-text"),
                        html.P("or click to select file", className="upload-subtext"),
                        html.P(f"Maximum file size: {CONFIG.get('max_file_size_mb', 50)}MB", 
                               className="upload-hint"),
                    ]),
                    multiple=False,  # Only one file at a time
                    max_size=CONFIG.get("max_file_size_mb", 50)*1024*1024,  # Use config value
                    className="upload-box"
                ),
                
                # Processing options
                html.Div([
                    html.Label("Processing Options:", className="options-label"),
                    
                    # Option 1: Approximation with inline info icon
                    html.Div([
                        dcc.Checklist(
                            id="processing-options",
                            options=[
                                {
                                    "label": " Use mandatory-field approximation",
                                    "value": "approx"
                                }
                            ],
                            value=[],
                            className="options-checklist-inline"
                        ),
                        html.Span(className="sap-icon sap-icon--info sap-icon--sm info-icon-inline",
                                 title="When enabled, documents with all mandatory fields at ≥70% confidence are automatically approved at 100%. Simplifies scoring for clear-cut cases."),
                    ], className="option-row"),
                    
                    # Option 2: Validation with inline info icon
                    html.Div([
                        dcc.Checklist(
                            id="processing-options-validation",
                            options=[
                                {
                                    "label": " Enable business rule validation",
                                    "value": "validate"
                                }
                            ],
                            value=[],
                            className="options-checklist-inline"
                        ),
                        html.Span(className="sap-icon sap-icon--info sap-icon--sm info-icon-inline",
                                 title="Runs additional validation checks beyond AI confidence, such as date freshness limits and authority whitelists. May downgrade approval status if rules fail."),
                    ], className="option-row"),
                ], className="options-panel"),
                
                # Upload status message
                html.Div(id="upload-status", className="upload-status"),
                
                # Progress indicator (hidden until upload starts)
                html.Div([
                    html.Div(
                        id="progress-bar", 
                        className="progress-bar",
                        children=[html.Span(id="progress-text", className="progress-text")]
                    ),
                ], id="progress-container", style={"display": "none", "backgroundColor": "#E5E5E5", "borderRadius": "2px", "height": "24px", "marginTop": "1.5rem", "position": "relative"}),
                
            ], className="upload-panel"),
            
            # ───────────────────────────────────────────────────────────────
            # Live Processing Logs (Collapsible with animations)
            # ───────────────────────────────────────────────────────────────
            html.Details([
                html.Summary([
                    html.Span(className="sap-icon sap-icon--slim-arrow-right collapse-arrow", id="log-arrow"),
                    html.Span(className="sap-icon sap-icon--log", style={"marginRight": "8px"}),
                    html.Span("PROCESSING LOGS"),
                    html.Span(id="log-status-badge", className="log-status-badge"),
                ], className="log-summary"),
                html.Div([
                    html.Div(id="live-log", className="log-container"),
                ], className="log-content")
            ], id="log-panel-section", className="log-panel", open=False),
            
        ], className="left-panel"),
        
        # ═══════════════════════════════════════════════════════════════════
        # RIGHT PANEL - RESULTS & ANALYSIS
        # ═══════════════════════════════════════════════════════════════════
        html.Div([
            
            # Welcome State (shown before any document is processed)
            html.Div([
                html.Div([
                    html.Div(className="sap-icon sap-icon--document-processing welcome-icon"),
                    html.H2("Ready to Validate Documents", className="welcome-title"),
                    html.P("Upload a UAE NOC document to begin AI-powered validation and extraction.", className="welcome-subtitle"),
                    html.Div([
                        html.Div([
                            html.Span(className="sap-icon sap-icon--upload feature-icon"),
                            html.Div([
                                html.Strong("Upload PDF"),
                                html.P("Drag & drop or click to select")
                            ], className="feature-text")
                        ], className="feature-item"),
                        html.Div([
                            html.Span(className="sap-icon sap-icon--parallel feature-icon"),
                            html.Div([
                                html.Strong("Parallel Processing"),
                                html.P("Split into chunks for faster extraction")
                            ], className="feature-text")
                        ], className="feature-item"),
                        html.Div([
                            html.Span(className="sap-icon sap-icon--ai feature-icon"),
                            html.Div([
                                html.Strong("AI Extraction"),
                                html.P("SAP DOX analyzes your document")
                            ], className="feature-text")
                        ], className="feature-item"),
                        html.Div([
                            html.Span(className="sap-icon sap-icon--analytics feature-icon"),
                            html.Div([
                                html.Strong("Confidence Scoring"),
                                html.P("Get detailed validation results")
                            ], className="feature-text")
                        ], className="feature-item"),
                    ], className="features-grid"),
                ], className="welcome-content")
            ], id="welcome-state", className="welcome-state", style={"display": "block"}),
            
            # Results Container (hidden until document is processed)
            html.Div([
                # Verdict Banner (Approved/Needs Review/Rejected)
                html.Div(id="verdict-banner", className="verdict-banner", 
                        style={"display": "none"}),
                
                # Confidence Gauge Chart (hidden during processing)
                html.Div([
                    dcc.Graph(id="confidence-gauge", className="gauge-chart", 
                             config={"displayModeBar": False}),
                ], id="gauge-container", className="gauge-container"),
            
            # ───────────────────────────────────────────────────────────────
            # Processing Flow Visualization (NEW!)
            # ───────────────────────────────────────────────────────────────
            html.Div(id="processing-flow-section", className="processing-flow-container",
                    style={"display": "none"}, children=[
                html.Div([
                    html.Span(className="sap-icon sap-icon--processing", style={"marginRight": "8px"}),
                    "PROCESSING PIPELINE"
                ], className="processing-flow-title"),
                html.Div(id="processing-flow-viz", className="processing-steps"),
            ]),
            
            # Explainability Summary (why this score?)
            html.Div(id="explainability-summary", className="explainability-panel"),
            
            # ───────────────────────────────────────────────────────────────
            # Document Review Section (Collapsible) - MOVED BELOW ANALYSIS
            # ───────────────────────────────────────────────────────────────
            html.Details([
                html.Summary([
                    html.Span(className="sap-icon sap-icon--slim-arrow-right collapse-arrow", id="preview-arrow"),
                    html.Span(className="sap-icon sap-icon--search", style={"marginRight": "8px"}),
                    html.Span("DOCUMENT PREVIEW")
                ], className="preview-summary"),
                html.Div([
                    # Document metadata row
                    html.Div(id="doc-metadata", className="doc-metadata"),
                    # Carousel container
                    html.Div([
                        # Previous button
                        html.Button("‹", id="carousel-prev", className="carousel-button carousel-prev"),
                        # Thumbnail images container (carousel)
                        html.Div(id="thumbnails-container", className="carousel-container"),
                        # Next button
                        html.Button("›", id="carousel-next", className="carousel-button carousel-next"),
                        # Page indicator
                        html.Div(id="carousel-indicator", className="carousel-indicator"),
                    ], className="carousel-wrapper"),
                ], className="preview-content")
            ], id="pdf-preview-section", className="preview-section", 
               style={"display": "none"}, open=False),
            
            # ───────────────────────────────────────────────────────────────
            # Mandatory Fields Table
            # ───────────────────────────────────────────────────────────────
            html.Div([
                html.H3([
                    html.Span(className="sap-icon sap-icon--list", style={"marginRight": "8px", "color": "var(--sap-brand-blue)"}),
                    "Mandatory Fields Evaluation"
                ], className="panel-title"),
                dash_table.DataTable(
                    id="table-mandatory",
                    style_table={"overflowX": "auto"},
                    style_header={
                        "backgroundColor": "var(--sap-blue-dark)",
                        "color": "white",
                        "fontWeight": "700",
                        "textAlign": "center"
                    },
                    style_cell={
                        "textAlign": "left",
                        "padding": "12px",
                        "fontFamily": "var(--sap-font-family)"
                    },
                    style_data_conditional=[
                        {
                            "if": {"filter_query": "{Confidence (%)} < 70"},
                            "backgroundColor": "var(--sap-warning-light)",
                            "color": "var(--sap-warning-dark)",
                        }
                    ],
                    page_size=10,  # Show 10 rows per page
                ),
            ], className="table-container"),
            
            # ───────────────────────────────────────────────────────────────
            # All Fields Table (Complete breakdown)
            # ───────────────────────────────────────────────────────────────
            html.Div([
                html.H3([
                    html.Span(className="sap-icon sap-icon--analytics", style={"marginRight": "8px", "color": "var(--sap-brand-blue)"}),
                    "All Extracted Fields"
                ], className="panel-title"),
                html.Div([
                    html.Span("● ", className="sap-success", style={"fontWeight": "bold"}),
                    html.Span("Weighted Field (contributes to score)", 
                             style={"color": "var(--sap-gray-7)", "fontSize": "0.875rem", "marginRight": "20px"}),
                    html.Span("○ ", style={"color": "var(--sap-gray-5)", "fontWeight": "bold"}),
                    html.Span("Informational Field (does not affect score)", 
                             style={"color": "var(--sap-gray-7)", "fontSize": "0.875rem"})
                ], style={"marginBottom": "10px"}),
                dash_table.DataTable(
                    id="table-explain",
                    style_table={"overflowX": "auto"},
                    style_header={
                        "backgroundColor": "var(--sap-blue-dark)",
                        "color": "white",
                        "fontWeight": "700",
                        "textAlign": "center"
                    },
                    style_cell={
                        "textAlign": "left",
                        "padding": "12px",
                        "fontFamily": "var(--sap-font-family)"
                    },
                    style_data_conditional=[
                        # Style for Weighted Fields (Green Border) - Make row bold
                        {
                            "if": {"filter_query": "{Row Color} = '#e6ffe6'"},
                            "backgroundColor": "var(--sap-success-light)",
                            "borderLeft": f"3px solid var(--sap-success)",
                            "fontWeight": "600"
                        },
                        # Style for Other Fields (Grey Border)
                        {
                            "if": {"filter_query": "{Row Color} = '#f7f7f7'"},
                            "backgroundColor": "var(--sap-gray-1)",
                            "borderLeft": f"3px solid var(--sap-gray-4)"
                        },
                        # Conditional formatting for low confidence (Error color only, not bold)
                        {
                            "if": {"filter_query": "{Confidence (%)} < 70"},
                            "color": "var(--sap-error)"
                        }
                    ],
                    page_size=15,
                    filter_action="native" if CONFIG.get("ui", {}).get("enable_filtering", True) else "none",
                    sort_action="native" if CONFIG.get("ui", {}).get("enable_sorting", True) else "none",
                ),
            ], className="table-container"),
            
            # ───────────────────────────────────────────────────────────────
            # Confidence Distribution Chart
            # ───────────────────────────────────────────────────────────────
            html.Div([
                html.H3([
                    html.Span(className="sap-icon sap-icon--analytics", style={"marginRight": "8px", "color": "var(--sap-brand-blue)"}),
                    "Field Confidence Distribution"
                ], className="panel-title", style={"marginTop": 0, "borderBottom": "none"}),
                dcc.Graph(id="graph-explain", className="confidence-chart"),
            ], className="chart-container"),
            
                # ───────────────────────────────────────────────────────────────
                # Raw JSON Output (for debugging/technical analysis)
                # ───────────────────────────────────────────────────────────────
                html.Details([
                    html.Summary([
                        html.Span(className="sap-icon sap-icon--slim-arrow-right collapse-arrow", id="json-arrow"),
                        html.Span(className="sap-icon sap-icon--document", style={"marginRight": "8px"}),
                        html.Span("VIEW DOCUMENT EXTRACTION JSON")
                    ], className="preview-summary json-summary"),
                    html.Pre(id="json-output", className="json-output")
                ], className="preview-section json-details", style={"display": "block" if CONFIG.get("ui", {}).get("show_raw_json", True) else "none"}),
              
            ], id="results-container", style={"display": "none"}),
            
        ], className="right-panel"),
        
    ], className="main-content"),
    ], id="tab-content-validator", className="tab-content"),
    
    # ═══════════════════════════════════════════════════════════════════════
    # TAB CONTENT: SCHEMA CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════
    html.Div([
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--schema sap-icon--lg", style={"color": "var(--sap-brand-blue)"}),
                    html.Span("Schema Configuration", style={"marginLeft": "12px", "fontWeight": "700", "fontSize": "1.125rem"})
                ], className="config-title"),
                html.Div([
                    html.Button([
                        html.Span(className="sap-icon sap-icon--download sap-icon--sm"),
                        " Download Config"
                    ], id="schema-download-btn", className="sap-button sap-button--ghost sap-button--sm"),
                    html.Button([
                        html.Span(className="sap-icon sap-icon--refresh sap-icon--sm"),
                        " Reset"
                    ], id="schema-reset-btn", className="sap-button sap-button--ghost sap-button--sm"),
                    html.Button([
                        html.Span(className="sap-icon sap-icon--save sap-icon--sm"),
                        " Save Changes"
                    ], id="schema-save-btn", className="sap-button sap-button--primary sap-button--sm"),
                ], className="config-actions")
            ], className="config-header"),
            
            html.Div([
                html.Div([
                    html.P("Configure the extraction schema for UAE NOC documents. Set field weights for confidence scoring, mark mandatory fields, and manage extraction fields. Changes affect how the AI extracts information from documents.")
                ], className="config-description"),
                
                html.Div(id="schema-fields-list", className="draggable-list"),
                
                html.Button([
                    html.Span(className="sap-icon sap-icon--add"),
                    " Add Field"
                ], id="add-schema-field-btn", className="add-item-button", n_clicks=0),
            ], className="config-body"),
        ], className="config-container"),
        
        # Add Field Modal Dialog
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--add sap-icon--lg", style={"color": "var(--sap-brand-blue)", "marginRight": "10px"}),
                    html.Span("Add New Schema Field", style={"fontWeight": "700", "fontSize": "1.1rem"})
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "1.5rem"}),
                
                # Form Fields
                html.Div([
                    html.Label("Field Name *", className="form-label"),
                    dcc.Input(id="new-field-name", type="text", placeholder="e.g., applicationNumber", className="form-input"),
                ], className="form-group"),
                
                html.Div([
                    html.Label("Description", className="form-label"),
                    dcc.Input(id="new-field-description", type="text", placeholder="Brief description of the field", className="form-input"),
                ], className="form-group"),
                
                html.Div([
                    html.Div([
                        html.Label("Field Type", className="form-label"),
                        dcc.Dropdown(
                            id="new-field-type",
                            options=[
                                {"label": "String", "value": "string"},
                                {"label": "Date", "value": "date"},
                                {"label": "Number", "value": "number"},
                                {"label": "Currency", "value": "currency"},
                            ],
                            value="string",
                            clearable=False,
                            className="form-dropdown"
                        ),
                    ], style={"flex": "1"}),
                    html.Div([
                        html.Label("Weight (%)", className="form-label"),
                        dcc.Input(id="new-field-weight", type="number", value=5, min=0, max=100, className="form-input"),
                    ], style={"flex": "1"}),
                ], className="form-row"),
                
                html.Div([
                    dcc.Checklist(
                        id="new-field-mandatory",
                        options=[{"label": " Mark as Mandatory Field", "value": "mandatory"}],
                        value=[],
                        className="form-checklist"
                    ),
                ], className="form-group"),
                
                html.Div([
                    html.Button("Cancel", id="add-field-cancel", className="dialog-button-cancel"),
                    html.Button("Add Field", id="add-field-confirm", className="dialog-button-confirm"),
                ], style={"display": "flex", "gap": "10px", "justifyContent": "flex-end", "marginTop": "1.5rem"})
            ], className="dialog-content modal-wide")
        ], id="add-field-modal", className="dialog-overlay", style={"display": "none"}),
        
        # Download Component
        dcc.Download(id="download-config"),
        
        # Edit Field Modal Dialog
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--edit sap-icon--lg", style={"color": "var(--sap-brand-blue)", "marginRight": "10px"}),
                    html.Span("Edit Schema Field", style={"fontWeight": "700", "fontSize": "1.1rem"})
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "1.5rem"}),
                
                # Hidden field to store the index being edited
                dcc.Store(id="edit-field-index", data=None),
                
                # Form Fields
                html.Div([
                    html.Label("Field Name", className="form-label"),
                    dcc.Input(id="edit-field-name", type="text", disabled=True, className="form-input", style={"background": "#f5f5f5"}),
                ], className="form-group"),
                
                html.Div([
                    html.Label("Description", className="form-label"),
                    dcc.Input(id="edit-field-description", type="text", className="form-input"),
                ], className="form-group"),
                
                html.Div([
                    html.Div([
                        html.Label("Field Type", className="form-label"),
                        dcc.Dropdown(
                            id="edit-field-type",
                            options=[
                                {"label": "String", "value": "string"},
                                {"label": "Date", "value": "date"},
                                {"label": "Number", "value": "number"},
                                {"label": "Currency", "value": "currency"},
                            ],
                            clearable=False,
                            className="form-dropdown"
                        ),
                    ], style={"flex": "1"}),
                    html.Div([
                        html.Label("Weight", className="form-label"),
                        dcc.Input(id="edit-field-weight", type="number", min=0, max=100, className="form-input"),
                    ], style={"flex": "1"}),
                ], className="form-row"),
                
                html.Div([
                    dcc.Checklist(
                        id="edit-field-mandatory",
                        options=[{"label": " Mark as Mandatory Field", "value": "mandatory"}],
                        value=[],
                        className="form-checklist"
                    ),
                ], className="form-group"),
                
                html.Div([
                    html.Button("Cancel", id="edit-field-cancel", className="dialog-button-cancel"),
                    html.Button("Save Changes", id="edit-field-save", className="dialog-button-confirm"),
                ], style={"display": "flex", "gap": "10px", "justifyContent": "flex-end", "marginTop": "1.5rem"})
            ], className="dialog-content modal-wide")
        ], id="edit-field-modal", className="dialog-overlay", style={"display": "none"}),
        
    ], id="tab-content-schema", className="tab-content", style={"display": "none", "padding": "1.5rem"}),
    
    # ═══════════════════════════════════════════════════════════════════════
    # TAB CONTENT: BUSINESS RULES CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════
    html.Div([
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--rules sap-icon--lg", style={"color": "var(--sap-brand-blue)"}),
                    html.Span("Business Rules Configuration", style={"marginLeft": "12px", "fontWeight": "700", "fontSize": "1.125rem"})
                ], className="config-title"),
                html.Div([
                    html.Button([
                        html.Span(className="sap-icon sap-icon--download sap-icon--sm"),
                        " Download Rules"
                    ], id="rules-download-btn", className="sap-button sap-button--ghost sap-button--sm"),
                    html.Button([
                        html.Span(className="sap-icon sap-icon--refresh sap-icon--sm"),
                        " Reset"
                    ], id="rules-reset-btn", className="sap-button sap-button--ghost sap-button--sm"),
                    html.Button([
                        html.Span(className="sap-icon sap-icon--save sap-icon--sm"),
                        " Save Changes"
                    ], id="rules-save-btn", className="sap-button sap-button--primary sap-button--sm"),
                ], className="config-actions")
            ], className="config-header"),
            
            html.Div([
                html.Div([
                    html.P("Configure validation rules that are applied after AI extraction. These rules can downgrade approval status if documents fail validation checks (e.g., date freshness, authority whitelists).")
                ], className="config-description"),
                
                html.Div(id="business-rules-list", className="draggable-list"),
                
                html.Button([
                    html.Span(className="sap-icon sap-icon--add"),
                    " Add Rule"
                ], id="add-rule-btn", className="add-item-button", n_clicks=0),
            ], className="config-body"),
        ], className="config-container"),
        
        # Add Rule Modal Dialog
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--add sap-icon--lg", style={"color": "var(--sap-brand-blue)", "marginRight": "10px"}),
                    html.Span("Add New Validation Rule", style={"fontWeight": "700", "fontSize": "1.1rem"})
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "1.5rem"}),
                
                # Form Fields
                html.Div([
                    html.Label("Target Field *", className="form-label"),
                    dcc.Dropdown(
                        id="new-rule-field",
                        options=[{"label": FRIENDLY_LABELS.get(f, f), "value": f} for f in ALL_FIELDS],
                        placeholder="Select field to validate",
                        className="form-dropdown"
                    ),
                ], className="form-group"),
                
                html.Div([
                    html.Label("Rule Type *", className="form-label"),
                    dcc.Dropdown(
                        id="new-rule-type",
                        options=[
                            {"label": "Date Age Limit", "value": "date_age"},
                            {"label": "Whitelist (Allowed Values)", "value": "whitelist"},
                        ],
                        placeholder="Select rule type",
                        className="form-dropdown"
                    ),
                ], className="form-group"),
                
                # Dynamic parameters based on rule type
                html.Div(id="rule-params-container", children=[
                    html.Div([
                        html.Label("Maximum Age (Months)", className="form-label"),
                        dcc.Input(id="new-rule-max-age", type="number", value=6, min=1, className="form-input"),
                    ], className="form-group"),
                ]),
                
                html.Div([
                    html.Label("Error Message", className="form-label"),
                    dcc.Input(id="new-rule-error", type="text", placeholder="e.g., Document is too old", className="form-input"),
                ], className="form-group"),
                
                html.Div([
                    html.Button("Cancel", id="add-rule-cancel", className="dialog-button-cancel"),
                    html.Button("Add Rule", id="add-rule-confirm", className="dialog-button-confirm"),
                ], style={"display": "flex", "gap": "10px", "justifyContent": "flex-end", "marginTop": "1.5rem"})
            ], className="dialog-content modal-wide")
        ], id="add-rule-modal", className="dialog-overlay", style={"display": "none"}),
        
        # Download Component for Rules
        dcc.Download(id="download-rules"),
        
        # Edit Rule Modal Dialog
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--edit sap-icon--lg", style={"color": "var(--sap-brand-blue)", "marginRight": "10px"}),
                    html.Span("Edit Validation Rule", style={"fontWeight": "700", "fontSize": "1.1rem"})
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "1.5rem"}),
                
                # Hidden store to track which rule is being edited
                dcc.Store(id="edit-rule-field-key", data=None),
                
                # Form Fields
                html.Div([
                    html.Label("Target Field", className="form-label"),
                    dcc.Input(id="edit-rule-field", type="text", disabled=True, className="form-input", style={"background": "#f5f5f5"}),
                ], className="form-group"),
                
                html.Div([
                    html.Label("Rule Type", className="form-label"),
                    dcc.Dropdown(
                        id="edit-rule-type",
                        options=[
                            {"label": "Date Age Limit", "value": "date_age"},
                            {"label": "Whitelist (Allowed Values)", "value": "whitelist"},
                        ],
                        clearable=False,
                        className="form-dropdown"
                    ),
                ], className="form-group"),
                
                # Dynamic parameters based on rule type
                html.Div(id="edit-rule-params-container", children=[]),
                
                html.Div([
                    html.Label("Error Message", className="form-label"),
                    dcc.Input(id="edit-rule-error", type="text", className="form-input"),
                ], className="form-group"),
                
                html.Div([
                    html.Button("Cancel", id="edit-rule-cancel", className="dialog-button-cancel"),
                    html.Button("Save Changes", id="edit-rule-save", className="dialog-button-confirm"),
                ], style={"display": "flex", "gap": "10px", "justifyContent": "flex-end", "marginTop": "1.5rem"})
            ], className="dialog-content modal-wide")
        ], id="edit-rule-modal", className="dialog-overlay", style={"display": "none"}),
        
    ], id="tab-content-rules", className="tab-content", style={"display": "none", "padding": "1.5rem"}),
    
    # ═══════════════════════════════════════════════════════════════════════
    # TAB CONTENT: DASHBOARD
    # ═══════════════════════════════════════════════════════════════════════
    html.Div([
        # Metrics Cards Row
        html.Div([
            # Total Documents Card
            html.Div([
                html.Div([
                    html.Span("Total Documents", className="metric-label"),
                    html.Div([html.Span(className="sap-icon sap-icon--document")], className="metric-icon total"),
                ], className="metric-header"),
                html.Div(id="metric-total", className="metric-value", children="0"),
                html.Div("All time processed", className="metric-trend"),
            ], className="metric-card"),
            
            # Approved Card
            html.Div([
                html.Div([
                    html.Span("Approved", className="metric-label"),
                    html.Div([html.Span(className="sap-icon sap-icon--success")], className="metric-icon approved"),
                ], className="metric-header"),
                html.Div(id="metric-approved", className="metric-value", children="0"),
                html.Div("Passed validation", className="metric-trend"),
            ], className="metric-card"),
            
            # Needs Review Card
            html.Div([
                html.Div([
                    html.Span("Needs Review", className="metric-label"),
                    html.Div([html.Span(className="sap-icon sap-icon--warning")], className="metric-icon review"),
                ], className="metric-header"),
                html.Div(id="metric-review", className="metric-value", children="0"),
                html.Div("Requires attention", className="metric-trend"),
            ], className="metric-card"),
            
            # Rejected Card
            html.Div([
                html.Div([
                    html.Span("Rejected", className="metric-label"),
                    html.Div([html.Span(className="sap-icon sap-icon--error")], className="metric-icon rejected"),
                ], className="metric-header"),
                html.Div(id="metric-rejected", className="metric-value", children="0"),
                html.Div("Failed validation", className="metric-trend"),
            ], className="metric-card"),
        ], className="metrics-grid"),
        
        # Document History Section
        html.Div([
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--history", style={"color": "var(--sap-brand-blue)"}),
                    html.Span("Document History", style={"marginLeft": "10px", "fontWeight": "600"})
                ], className="history-title"),
                html.Div([
                    html.Button([
                        html.Span(className="sap-icon sap-icon--refresh sap-icon--sm"),
                        " Clear All"
                    ], id="clear-history-btn", className="sap-button sap-button--ghost sap-button--sm"),
                    html.Button([
                        html.Span(className="sap-icon sap-icon--delete sap-icon--sm"),
                        " Delete All"
                    ], id="cleanup-button", className="sap-button sap-button--negative sap-button--sm", n_clicks=0),
                ], className="history-actions"),
            ], className="history-header"),
            
            # Cleanup Status Message (for SAP DOX document deletion feedback)
            # Auto-fades after 60 seconds via CSS animation
            html.Div(id="cleanup-status-message", className="cleanup-status-message"),
            
            # Status Filter Buttons
            html.Div([
                html.Button([
                    html.Span(className="sap-icon sap-icon--list sap-icon--sm", style={"marginRight": "6px"}),
                    "All"
                ], id="filter-all", className="filter-btn filter-btn--active", n_clicks=0),
                html.Button([
                    html.Span(className="sap-icon sap-icon--success sap-icon--sm", style={"marginRight": "6px"}),
                    "Approved"
                ], id="filter-approved", className="filter-btn filter-btn--approved", n_clicks=0),
                html.Button([
                    html.Span(className="sap-icon sap-icon--warning sap-icon--sm", style={"marginRight": "6px"}),
                    "Needs Review"
                ], id="filter-review", className="filter-btn filter-btn--review", n_clicks=0),
                html.Button([
                    html.Span(className="sap-icon sap-icon--error sap-icon--sm", style={"marginRight": "6px"}),
                    "Rejected"
                ], id="filter-rejected", className="filter-btn filter-btn--rejected", n_clicks=0),
            ], className="status-filters"),
            
            # Search and Sort Controls
            html.Div([
                html.Div([
                    html.Span(className="sap-icon sap-icon--search", style={"position": "absolute", "left": "12px", "top": "50%", "transform": "translateY(-50%)", "color": "var(--sap-text-secondary)"}),
                    dcc.Input(
                        id="history-search",
                        type="text",
                        placeholder="Search documents...",
                        className="search-input",
                        debounce=True
                    ),
                ], className="search-container"),
                html.Div([
                    dcc.Dropdown(
                        id="history-sort",
                        options=[
                            {"label": "Date (Newest)", "value": "date_desc"},
                            {"label": "Date (Oldest)", "value": "date_asc"},
                            {"label": "Processing Time (Fastest)", "value": "time_asc"},
                            {"label": "Processing Time (Slowest)", "value": "time_desc"},
                            {"label": "Status", "value": "status"},
                            {"label": "Confidence (Highest)", "value": "conf_desc"},
                            {"label": "Confidence (Lowest)", "value": "conf_asc"},
                        ],
                        value="date_desc",
                        clearable=False,
                        className="sort-dropdown",
                        placeholder="Sort by..."
                    ),
                ], className="sort-container"),
            ], className="history-controls"),
            
            # Hidden store for active filter
            dcc.Store(id="active-status-filter", data="all"),
            
            html.Div(id="document-history-list", children=[
                html.Div([
                    html.Span(className="sap-icon sap-icon--document sap-icon--xxl"),
                    html.Div("No documents processed yet", className="history-empty-text"),
                    html.Div("Upload a document to get started", className="history-empty-subtext"),
                ], className="history-empty")
            ]),
        ], className="history-container"),
    ], id="tab-content-dashboard", className="tab-content", style={"display": "none", "padding": "1.5rem"}),
    
    # ───────────────────────────────────────────────────────────────────────
    # HIDDEN COMPONENTS - Data storage and update triggers
    # ───────────────────────────────────────────────────────────────────────
    dcc.Store(id="current-job-id", data=None),      # Stores current job ID
    dcc.Store(id="job-result-store", data=None),    # Stores job results
    dcc.Store(id="pdf-content-store", data=None),   # Stores uploaded PDF content
    dcc.Store(id="carousel-index", data=0),         # Current carousel page index
    dcc.Store(id="carousel-total", data=0),         # Total number of pages in carousel
    dcc.Store(id="active-tab", data="validator"),   # Current active tab
    dcc.Store(id="document-history", data=[]),      # Document history storage
    dcc.Store(id="custom-fields", data=[]),         # Custom schema fields added by user
    dcc.Store(id="custom-rules", data={}),          # Custom validation rules added by user
    dcc.Interval(id="poll-interval", interval=1000, disabled=True),  # 1 sec polling
    
], className="app-container")

# ═══════════════════════════════════════════════════════════════════════════
# DASH CALLBACKS - REACTIVE EVENT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════
# Callbacks define how the UI responds to user interactions.
# When an Input changes, the callback function runs and updates Outputs.

@dash_app.callback(
    Output("config-status", "children"),
    Input("poll-interval", "n_intervals"),
    prevent_initial_call=False
)
def update_config_status(_):
    """
    Update configuration status badge
    
    Shows whether SAP DOX is properly configured.
    Runs on app load and periodically during polling.
    
    Returns:
        HTML: Status indicator with icon
    """
    if config_valid:
        return html.Span([
            html.Span(className="status-dot connected"),
            " SAP DOX AI Connected"
        ], className="status-indicator")
    else:
        return html.Span([
            html.Span(className="status-dot warning"),
            " SAP DOX Not Configured"
        ], className="status-indicator")


@dash_app.callback(
    [Output("tab-content-validator", "style"),
     Output("tab-content-schema", "style"),
     Output("tab-content-rules", "style"),
     Output("tab-content-dashboard", "style"),
     Output("tab-validator", "className"),
     Output("tab-schema", "className"),
     Output("tab-rules", "className"),
     Output("tab-dashboard", "className"),
     Output("active-tab", "data")],
    [Input("tab-validator", "n_clicks"),
     Input("tab-schema", "n_clicks"),
     Input("tab-rules", "n_clicks"),
     Input("tab-dashboard", "n_clicks")],
    prevent_initial_call=True
)
def switch_tabs(validator_clicks, schema_clicks, rules_clicks, dashboard_clicks):
    """
    Handle tab switching between Validator, Schema Config, Business Rules, and Dashboard
    """
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    # Default styles (all hidden)
    styles = {
        "validator": {"display": "none"},
        "schema": {"display": "none", "padding": "1.5rem"},
        "rules": {"display": "none", "padding": "1.5rem"},
        "dashboard": {"display": "none", "padding": "1.5rem"}
    }
    
    # Default classes (all inactive)
    classes = {
        "validator": "tab-button",
        "schema": "tab-button",
        "rules": "tab-button",
        "dashboard": "tab-button"
    }
    
    # Show selected tab
    if trigger_id == "tab-validator":
        styles["validator"] = {"display": "block"}
        classes["validator"] = "tab-button active"
        active = "validator"
    elif trigger_id == "tab-schema":
        styles["schema"] = {"display": "block", "padding": "1.5rem"}
        classes["schema"] = "tab-button active"
        active = "schema"
    elif trigger_id == "tab-rules":
        styles["rules"] = {"display": "block", "padding": "1.5rem"}
        classes["rules"] = "tab-button active"
        active = "rules"
    elif trigger_id == "tab-dashboard":
        styles["dashboard"] = {"display": "block", "padding": "1.5rem"}
        classes["dashboard"] = "tab-button active"
        active = "dashboard"
    else:
        raise PreventUpdate
    
    return (
        styles["validator"],
        styles["schema"],
        styles["rules"],
        styles["dashboard"],
        classes["validator"],
        classes["schema"],
        classes["rules"],
        classes["dashboard"],
        active
    )

@dash_app.callback(
    Output("cleanup-dialog", "style"),
    [Input("cleanup-button", "n_clicks"),
     Input("cleanup-cancel", "n_clicks")],
    prevent_initial_call=True
)
def toggle_cleanup_dialog(cleanup_clicks, cancel_clicks):
    """
    Show/hide cleanup confirmation dialog
    
    Args:
        cleanup_clicks (int): Number of times cleanup button clicked
        cancel_clicks (int): Number of times cancel button clicked
        
    Returns:
        dict: Style to show or hide dialog
    """
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if trigger_id == "cleanup-button":
        # Show dialog
        return {"display": "flex"}
    elif trigger_id == "cleanup-cancel":
        # Hide dialog
        return {"display": "none"}
    
    raise PreventUpdate

@dash_app.callback(
    [Output("cleanup-trigger", "data"),
     Output("cleanup-dialog", "style", allow_duplicate=True),
     Output("cleanup-status-message", "children")],
    Input("cleanup-confirm", "n_clicks"),
    prevent_initial_call=True
)
def confirm_cleanup(n_clicks):
    """
    Execute cleanup when user confirms
    
    This calls the delete-all API endpoint and shows the result.
    
    Args:
        n_clicks (int): Number of times confirm button clicked
        
    Returns:
        tuple: (trigger_value, dialog_style, status_message)
    """
    if not n_clicks:
        raise PreventUpdate
    
    try:
        # Call the delete-all endpoint
        response = requests.post(f"http://localhost:{APP_PORT}/api/dox/documents/delete-all")
        result = response.json()
        
        # Hide dialog
        dialog_style = {"display": "none"}
        
        # Show result message with SAP icons
        if response.status_code == 200:
            deleted_count = result.get("deleted_documents", 0)
            if deleted_count > 0:
                status_msg = html.Span([
                    html.Span(className="sap-icon sap-icon--delete sap-icon--sm", style={"marginRight": "8px", "color": "var(--sap-success)"}),
                    f"Successfully deleted {deleted_count} documents from SAP DOX"
                ])
            else:
                status_msg = html.Span([
                    html.Span(className="sap-icon sap-icon--info sap-icon--sm", style={"marginRight": "8px", "color": "var(--sap-brand-blue)"}),
                    "No documents found to delete"
                ])
        else:
            status_msg = html.Span([
                html.Span(className="sap-icon sap-icon--warning sap-icon--sm", style={"marginRight": "8px", "color": "var(--sap-warning)"}),
                f"Cleanup failed: {result.get('error', 'Unknown error')}"
            ])
        
        return (n_clicks, dialog_style, status_msg)
        
    except Exception as e:
        return (n_clicks, {"display": "none"}, html.Span([
            html.Span(className="sap-icon sap-icon--error sap-icon--sm", style={"marginRight": "8px", "color": "var(--sap-error)"}),
            f"Cleanup error: {str(e)}"
        ]))

@dash_app.callback(
    [Output("current-job-id", "data"),
     Output("poll-interval", "disabled"),
     Output("upload-status", "children"),
     Output("progress-container", "style"),
     Output("upload-pdf", "disabled"),
     Output("welcome-state", "style", allow_duplicate=True),
     Output("results-container", "style", allow_duplicate=True),
     Output("verdict-banner", "style", allow_duplicate=True),
     Output("gauge-container", "style", allow_duplicate=True),
     Output("confidence-gauge", "figure", allow_duplicate=True),
     Output("explainability-summary", "children", allow_duplicate=True),
     Output("table-mandatory", "data", allow_duplicate=True),
     Output("table-explain", "data", allow_duplicate=True),
     Output("graph-explain", "figure", allow_duplicate=True),
     Output("json-output", "children", allow_duplicate=True)],
    [Input("upload-pdf", "contents")],
    [State("upload-pdf", "filename"),
     State("processing-options", "value"),
     State("processing-options-validation", "value")],
    prevent_initial_call=True
)
def start_processing(content, filename, options_value_approx, options_value_validation):
    """
    Start async processing when user uploads a file
    
    This callback is triggered when a file is uploaded to the dcc.Upload
    component. It:
        1. Validates the upload
        2. Creates a new processing job
        3. Decodes the uploaded file
        4. Starts background processing thread
        5. Enables polling to track progress
    
    Args:
        content (str): Base64-encoded file content
        filename (str): Original filename
        options_value_approx (list): Approximation checklist value
        options_value_validation (list): Validation checklist value
        
    Returns:
        tuple: (job_id, poll_enabled, status_msg, progress_style, upload_disabled)
    """
    if not content:
        raise PreventUpdate  # No file uploaded yet
    
    # Validate SAP DOX configuration
    if not config_valid:
        return (
            None,  # No job ID
            True,  # Polling disabled
            "SAP DOX not configured. Please check your settings.",
            {"display": "none"},  # Hide progress bar
            False, # Enable upload button
            {"display": "block"},  # Keep welcome state visible
            {"display": "none"},   # Hide results container
            {"display": "none"},  # Hide verdict banner
            {"display": "block"},  # Show gauge container (for error state)
            go.Figure(),
            no_update,
            [],
            [],
            go.Figure(),
            ""
        )
    
    # ───────────────────────────────────────────────────────────────────────
    # CREATE NEW PROCESSING JOB
    # ───────────────────────────────────────────────────────────────────────
    job_id = str(uuid.uuid4())  # Generate unique ID
    job = ProcessingJob(job_id)
    job.add_log(f"📁 File received: {filename}")
    
    # Store job in global dictionary (thread-safe)
    with job_lock:
        processing_jobs[job_id] = job
    
    # ───────────────────────────────────────────────────────────────────────
    # DECODE UPLOADED FILE
    # ───────────────────────────────────────────────────────────────────────
    # dcc.Upload sends files as base64-encoded strings with data URI prefix
    # Format: "data:application/pdf;base64,<encoded_content>"
    try:
        file_bytes = base64.b64decode(content.split(",")[1])
    except Exception as e:
        return (
            None, 
            True, 
            f"Failed to decode file: {e}", 
            {"display": "none"}, 
            False,
            {"display": "block"},  # Keep welcome state visible
            {"display": "none"},   # Hide results container
            {"display": "none"},
            {"display": "block"},  # Show gauge container (for error state)
            go.Figure(),
            no_update,
            [],
            [],
            go.Figure(),
            ""
        )
    
    # ───────────────────────────────────────────────────────────────────────
    # START BACKGROUND PROCESSING THREAD
    # ───────────────────────────────────────────────────────────────────────
    # Combine values from both checklists
    use_approx = "approx" in (options_value_approx or [])
    use_validation = "validate" in (options_value_validation or [])
    
    thread = threading.Thread(
        target=process_document_async,
        args=(job_id, file_bytes, filename, use_approx, use_validation)
    )
    thread.daemon = True  # Thread will close when main program exits
    thread.start()
    
    # ───────────────────────────────────────────────────────────────────────
    # CLEAR PREVIOUS RESULTS (AUTO-REFRESH)
    # ───────────────────────────────────────────────────────────────────────
    
    # Empty gauge chart
    empty_gauge = go.Figure()
    empty_gauge.update_layout(
        margin=dict(l=20, r=20, t=60, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        height=250,
        annotations=[{
            'text': 'Processing...',
            'xref': 'paper',
            'yref': 'paper',
            'x': 0.5,
            'y': 0.5,
            'showarrow': False,
            'font': {'size': 20, 'color': '#999'}
        }]
    )
    
    # Empty bar chart
    empty_chart = go.Figure()
    empty_chart.update_layout(
        margin=dict(l=200, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        annotations=[{
            'text': 'Awaiting results...',
            'xref': 'paper',
            'yref': 'paper',
            'x': 0.5,
            'y': 0.5,
            'showarrow': False,
            'font': {'size': 16, 'color': '#999'}
        }]
    )
    
    # Return updated UI state with cleared results
    return (
        job_id,  # Store job ID for polling
        False,   # Enable polling (poll_interval.disabled = False)
        html.Span([
            html.Span(className="sap-icon sap-icon--processing", style={"marginRight": "8px", "animation": "spin 1s linear infinite"}),
            f"Processing {filename}..."
        ]),
        {"display": "block"},  # Show progress bar
        True,    # Disable upload button during processing
        {"display": "none"},   # Hide welcome state when processing starts
        {"display": "block"},  # Show results container
        {"display": "none"},  # Hide verdict banner
        {"display": "none"},  # Hide gauge container during processing
        empty_gauge,          # Clear gauge chart
        html.Div([
            html.Span(className="sap-icon sap-icon--processing sap-icon--lg", style={"marginRight": "10px", "animation": "spin 1s linear infinite", "color": "var(--sap-brand-blue)"}),
            "Processing document..."
        ], style={"textAlign": "center", "color": "var(--sap-gray-7)", "display": "flex", "alignItems": "center", "justifyContent": "center"}),  # Clear summary
        [],      # Clear mandatory table data
        [],      # Clear all fields table data
        empty_chart,  # Clear bar chart
        ""       # Clear JSON output
    )

@dash_app.callback(
    [Output("processing-flow-section", "style"),
     Output("processing-flow-viz", "children")],
    [Input("poll-interval", "n_intervals")],
    [State("current-job-id", "data")],
    prevent_initial_call=True
)
def update_processing_flow(n_intervals, job_id):
    """
    Update the processing flow visualization based on job progress
    
    Shows animated step indicators for:
    1. Document Upload
    2. AI Extraction
    3. Confidence Calculation
    4. Validation (if enabled)
    5. Results Ready
    
    Args:
        n_intervals (int): Polling interval trigger
        job_id (str): Current job ID
        
    Returns:
        tuple: (section_style, flow_viz_html)
    """
    if not job_id:
        # Hide flow when no job active
        return {"display": "none"}, []
    
    with job_lock:
        job = processing_jobs.get(job_id)
        if not job:
            return {"display": "none"}, []
    
    # Show flow section
    section_style = {"display": "block"}
    
    # Define processing steps with their progress thresholds (using SAP icon classes)
    steps = [
        {"label": "Upload", "icon_class": "sap-icon--upload", "threshold": 20},
        {"label": "AI Extract", "icon_class": "sap-icon--ai", "threshold": 70},
        {"label": "Calculate", "icon_class": "sap-icon--analytics", "threshold": 80},
        {"label": "Validate", "icon_class": "sap-icon--validate", "threshold": 90},
        {"label": "Complete", "icon_class": "sap-icon--success", "threshold": 100}
    ]
    
    # Determine status of each step based on job progress
    step_elements = []
    progress = job.progress
    status = job.status
    
    for i, step in enumerate(steps):
        # Determine step state
        if status == "failed":
            step_class = "processing-step step-failed" if progress >= step["threshold"] else "processing-step step-pending"
        elif progress >= step["threshold"]:
            step_class = "processing-step step-completed"
        elif progress >= (steps[i-1]["threshold"] if i > 0 else 0):
            step_class = "processing-step step-active"
        else:
            step_class = "processing-step step-pending"
        
        # Create step element with SAP icon
        step_elements.append(
            html.Div([
                html.Div([
                    html.Span(className=f"sap-icon {step['icon_class']}")
                ], className="step-circle"),
                html.Div(step["label"], className="step-label")
            ], className=step_class)
        )
    
    # Calculate progress line width
    if progress >= 100:
        line_width = "100%"
    else:
        line_width = f"{progress}%"
    
    # Build complete flow visualization
    flow_viz = [
        html.Div(className="progress-line", style={"width": line_width}),
        *step_elements
    ]
    
    return section_style, flow_viz

@dash_app.callback(
    [Output("pdf-preview-section", "style"),
     Output("thumbnails-container", "children"),
     Output("doc-metadata", "children"),
     Output("carousel-total", "data"),
     Output("carousel-index", "data"),
     Output("carousel-indicator", "children", allow_duplicate=True),
     Output("carousel-prev", "disabled", allow_duplicate=True),
     Output("carousel-next", "disabled", allow_duplicate=True)],
    [Input("job-result-store", "data")],
    prevent_initial_call=True
)
def update_preview_section(job_data):
    """
    Update document preview section with carousel and metadata
    
    This callback displays a carousel of page thumbnails and key metadata
    when processing completes successfully.
    
    Args:
        job_data (dict): Complete job data including results
        
    Returns:
        tuple: (section_style, carousel_html, metadata, total_pages, current_index)
    """
    if not job_data or job_data.get("status") != "completed":
        # Hide preview section if no results
        return (
            {"display": "none"},
            [],
            "",
            0,
            0,
            "",
            True,
            True
        )
    
    result = job_data.get("result", {})
    if not result:
        return (
            {"display": "none"},
            [],
            "",
            0,
            0,
            "",
            True,
            True
        )
    
    # Extract metadata
    filename = result.get("filename", "Unknown")
    num_pages = result.get("num_pages", 0)
    file_size_mb = result.get("file_size_mb", 0)
    processing_time = result.get("processing_time", 0)
    thumbnails = result.get("thumbnails", [])
    
    # Build metadata display with SAP icons
    metadata_content = html.Div([
        html.Div([
            html.Span(className="sap-icon sap-icon--document sap-icon--sm", style={"marginRight": "6px", "color": "var(--sap-brand-blue)"}),
            html.Strong("Filename: "),
            html.Span(filename)
        ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"}),
        html.Div([
            html.Span(className="sap-icon sap-icon--pages sap-icon--sm", style={"marginRight": "6px", "color": "var(--sap-brand-blue)"}),
            html.Strong("Pages: "),
            html.Span(f"{num_pages}"),
            html.Span(" | ", style={"margin": "0 10px", "color": "var(--sap-gray-5)"}),
            html.Span(className="sap-icon sap-icon--storage sap-icon--sm", style={"marginRight": "6px", "color": "var(--sap-brand-blue)"}),
            html.Strong("Size: "),
            html.Span(f"{file_size_mb} MB"),
            html.Span(" | ", style={"margin": "0 10px", "color": "var(--sap-gray-5)"}),
            html.Span(className="sap-icon sap-icon--clock sap-icon--sm", style={"marginRight": "6px", "color": "var(--sap-brand-blue)"}),
            html.Strong("Processing Time: "),
            html.Span(f"{processing_time}s")
        ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"})
    ])
    
    # Build carousel display - show only first thumbnail initially
    carousel_content = []
    if thumbnails:
        # Display only the first page (index 0) initially
        thumb_b64 = thumbnails[0]
        carousel_content = html.Div([
            html.Div(f"Page 1", className="thumbnail-label"),
            html.Img(
                src=f"data:image/png;base64,{thumb_b64}",
                className="pdf-thumbnail pdf-thumbnail-zoomable carousel-image",
                title=f"Click to zoom - Page 1"
            )
        ], className="carousel-slide")
    
    # Show preview section
    section_style = {"display": "block"}
    
    # Initialize carousel indicator and buttons
    total_thumb_pages = len(thumbnails)
    indicator_text = f"Page 1 of {total_thumb_pages}" if total_thumb_pages > 0 else ""
    prev_disabled = True  # Disable prev on first page
    next_disabled = (total_thumb_pages <= 1)  # Disable next if only 1 page
    
    return (
        section_style,
        carousel_content,
        metadata_content,
        total_thumb_pages,  # Total number of pages
        0,  # Start at first page (index 0)
        indicator_text,  # Initialize indicator
        prev_disabled,   # Initialize prev button state
        next_disabled    # Initialize next button state
    )

@dash_app.callback(
    [Output("thumbnails-container", "children", allow_duplicate=True),
     Output("carousel-index", "data", allow_duplicate=True),
     Output("carousel-indicator", "children"),
     Output("carousel-prev", "disabled"),
     Output("carousel-next", "disabled")],
    [Input("carousel-prev", "n_clicks"),
     Input("carousel-next", "n_clicks")],
    [State("carousel-index", "data"),
     State("carousel-total", "data"),
     State("job-result-store", "data")],
    prevent_initial_call=True
)
def navigate_carousel(prev_clicks, next_clicks, current_index, total_pages, job_data):
    """
    Handle carousel navigation (previous/next buttons)
    
    Args:
        prev_clicks (int): Number of times prev button clicked
        next_clicks (int): Number of times next button clicked
        current_index (int): Current page index (0-based)
        total_pages (int): Total number of pages in carousel
        job_data (dict): Job data containing thumbnails
        
    Returns:
        tuple: (new_carousel_content, new_index, indicator_text, prev_disabled, next_disabled)
    """
    if not job_data or total_pages == 0:
        raise PreventUpdate
    
    result = job_data.get("result", {})
    thumbnails = result.get("thumbnails", [])
    
    if not thumbnails:
        raise PreventUpdate
    
    # Determine which button was clicked
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    # Calculate new index
    new_index = current_index
    if trigger_id == "carousel-prev" and current_index > 0:
        new_index = current_index - 1
    elif trigger_id == "carousel-next" and current_index < total_pages - 1:
        new_index = current_index + 1
    
    # Build carousel content for new index
    thumb_b64 = thumbnails[new_index]
    carousel_content = html.Div([
        html.Div(f"Page {new_index + 1}", className="thumbnail-label"),
        html.Img(
            src=f"data:image/png;base64,{thumb_b64}",
            className="pdf-thumbnail pdf-thumbnail-zoomable carousel-image",
            title=f"Click to zoom - Page {new_index + 1}"
        )
    ], className="carousel-slide")
    
    # Update indicator
    indicator_text = f"Page {new_index + 1} of {total_pages}"
    
    # Disable buttons at boundaries
    prev_disabled = (new_index == 0)
    next_disabled = (new_index == total_pages - 1)
    
    return (
        carousel_content,
        new_index,
        indicator_text,
        prev_disabled,
        next_disabled
    )

@dash_app.callback(
    [Output("live-log", "children"),
     Output("progress-bar", "style"),
     Output("progress-text", "children"),
     Output("job-result-store", "data"),
     Output("poll-interval", "disabled", allow_duplicate=True),
     Output("upload-pdf", "disabled", allow_duplicate=True),
     Output("upload-status", "children", allow_duplicate=True),
     Output("upload-pdf", "contents"),  # Clear upload component
     Output("log-status-badge", "children"),  # Update status badge
     Output("log-status-badge", "className")],  # Update badge style
    [Input("poll-interval", "n_intervals")],
    [State("current-job-id", "data")],
    prevent_initial_call=True
)
def poll_job_status(n_intervals, job_id):
    """
    Poll job status and update UI in real-time
    
    This callback runs every second (when poll-interval is enabled) to:
        - Update processing logs
        - Update progress bar
        - Check if job is complete
        - Store results when done
    
    Args:
        n_intervals (int): Number of times interval has fired
        job_id (str): Current job ID being processed
        
    Returns:
        tuple: Updated UI components (logs, progress, results, etc.)
    """
    if not job_id:
        raise PreventUpdate  # No active job
    
    # Get job object (thread-safe)
    with job_lock:
        job = processing_jobs.get(job_id)
        if not job:
            raise PreventUpdate  # Job not found
    
    # Update logs display (ensure logs start with a new line for better formatting)
    logs_html = ("\n".join(job.logs)) if job.logs else "Waiting for logs..."

    
    # Update progress bar
    progress_style = {"width": f"{job.progress}%"}
    progress_text = f"{job.progress}%"
    
    # ───────────────────────────────────────────────────────────────────────
    # Update status badge based on job status
    # ───────────────────────────────────────────────────────────────────────
    status_badge_map = {
        "queued": ("IDLE", "log-status-badge log-status-idle"),
        "processing": ("PROCESSING", "log-status-badge log-status-processing"),
        "completed": ("COMPLETED", "log-status-badge log-status-completed"),
        "failed": ("FAILED", "log-status-badge log-status-failed")
    }
    
    badge_text, badge_class = status_badge_map.get(job.status, ("UNKNOWN", "log-status-badge log-status-idle"))
    
    # ───────────────────────────────────────────────────────────────────────
    # Check if job is complete (success or failure)
    # ───────────────────────────────────────────────────────────────────────
    if job.status in ("completed", "failed"):
        # Stop polling and update final status with SAP icons
        if job.status == "completed":
            status_msg = html.Span([
                html.Span(className="sap-icon sap-icon--success sap-icon--sm", style={"marginRight": "8px", "color": "var(--sap-success)"}),
                f"Processing complete: {job.result.get('filename', 'document')}"
            ])
        else:
            status_msg = html.Span([
                html.Span(className="sap-icon sap-icon--error sap-icon--sm", style={"marginRight": "8px", "color": "var(--sap-error)"}),
                f"Processing failed: {job.error}"
            ])
        
        # IMPORTANT: Return ALL 10 outputs to prevent infinite loop
        return (
            logs_html,           # 1. Updated logs
            progress_style,      # 2. Final progress bar
            progress_text,       # 3. Final progress text
            job.to_dict(),       # 4. Store complete results
            True,                # 5. Disable polling (job done)
            False,               # 6. Enable upload button
            status_msg,          # 7. Final status message
            None,                # 8. Clear upload contents to allow new upload
            badge_text,          # 9. Update status badge text
            badge_class          # 10. Update status badge styling
        )
    
    # Job still processing, return updated values
    return (
        logs_html,       # 1. Updated logs
        progress_style,  # 2. Progress bar style
        progress_text,   # 3. Progress text
        no_update,       # 4. Don't update results yet
        no_update,       # 5. Keep polling enabled
        no_update,       # 6. Keep upload disabled
        no_update,       # 7. Keep status message
        no_update,       # 8. Don't clear upload yet
        badge_text,      # 9. Update status badge text
        badge_class      # 10. Update status badge styling
    )

@dash_app.callback(
    [Output("welcome-state", "style"),
     Output("results-container", "style"),
     Output("verdict-banner", "children"),
     Output("verdict-banner", "style"),
     Output("gauge-container", "style"),
     Output("confidence-gauge", "figure"),
     Output("explainability-summary", "children"),
     Output("table-mandatory", "data"),
     Output("table-mandatory", "columns"),
     Output("table-explain", "data"),
     Output("table-explain", "columns"),
     Output("graph-explain", "figure"),
     Output("json-output", "children")],
    [Input("job-result-store", "data")],
    prevent_initial_call=True
)
def update_results(job_data):
    """
    Update all result visualizations when job completes
    
    This callback is triggered when job-result-store is updated (job done).
    It creates all the visualizations:
        - Verdict banner (Approved/Needs Review/Rejected)
        - Confidence gauge chart
        - Explainability summary
        - Data tables
        - Bar chart
        - Raw JSON
    
    Args:
        job_data (dict): Complete job data including results
        
    Returns:
        tuple: All updated visualization components
    """
    if not job_data or job_data.get("status") != "completed":
        raise PreventUpdate  # Only update when job completes successfully
    
    result = job_data.get("result", {})
    if not result:
        raise PreventUpdate
    
    # Extract result data
    conf = result.get("confidence", 0)
    status = result.get("status", "Unknown")
    breakdown = result.get("breakdown", [])
    filename = result.get("filename", "document")
    num_pages = result.get("num_pages", 0)
    raw_results = result.get("raw_results", [])
    fields = result.get("fields", {})
    validation_result = result.get("validation_result")  # May be None if validation not enabled
    
    # ───────────────────────────────────────────────────────────────────────
    # VERDICT BANNER
    # ───────────────────────────────────────────────────────────────────────
    # Define colors for each status with subtle pastel backgrounds
    verdict_styles = {
        "Approved": {
            "borderLeftColor": "#107E3E",        # Dark green border
            "backgroundColor": "#E8F5E9",        # Very light green pastel
            "color": "#1B5E20"                   # Dark green text
        },
        "Needs Review": {
            "borderLeftColor": "#F57C00",        # Orange border
            "backgroundColor": "#FFF3E0",        # Very light orange pastel
            "color": "#E65100"                   # Dark orange text
        },
        "Rejected": {
            "borderLeftColor": "#D32F2F",        # Red border
            "backgroundColor": "#FFEBEE",        # Very light red pastel
            "color": "#B71C1C"                   # Dark red text
        }
    }
    
    status_style = verdict_styles.get(status, {
        "borderLeftColor": "#6A6D70",
        "backgroundColor": "#F5F5F5",
        "color": "#32363A"
    })
    
    verdict_style = {
        "display": "block",
        "backgroundColor": status_style["backgroundColor"],
        "color": status_style["color"],
        "borderLeftColor": status_style["borderLeftColor"]
    }
    verdict_text = f"{status} • {conf*100:.1f}% Confidence"
    
    # ───────────────────────────────────────────────────────────────────────
    # CONFIDENCE GAUGE CHART
    # ───────────────────────────────────────────────────────────────────────
    # A circular gauge showing confidence score with color-coded regions
    
    approval_threshold = CONFIG.get("approval_threshold", 0.75)
    review_threshold = CONFIG.get("review_threshold", 0.6)
    
    gauge_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(conf * 100, 1),
        number={'suffix': "%", 'font': {'size': 40}},
        title={'text': "Overall Confidence Score", 'font': {'size': 18}},
        domain={'x': [0, 1], 'y': [0, 1]},
        gauge={
            'axis': {'range': [None, 100], 'tickwidth': 1},
            'bar': {'color': status_style["borderLeftColor"], 'thickness': 0.3},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "#ddd",
            # Color-coded regions (using muted colors)
            'steps': [
                {'range': [0, review_threshold * 100], 
                 'color': 'rgba(139, 74, 74, 0.15)'},  # Muted red zone: Rejected
                {'range': [review_threshold * 100, approval_threshold * 100], 
                 'color': 'rgba(184, 134, 11, 0.15)'},  # Muted gold zone: Needs Review
                {'range': [approval_threshold * 100, 100], 
                 'color': 'rgba(16, 126, 62, 0.15)'}   # Green zone: Approved
            ],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': round(conf * 100, 1)
            }
        }
    ))
    gauge_fig.update_layout(
        margin=dict(l=20, r=20, t=60, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        height=250
    )
    
    # ───────────────────────────────────────────────────────────────────────
    # EXPLAINABILITY SUMMARY
    # ───────────────────────────────────────────────────────────────────────
    # Explain WHY the document got this score
    
    # Find problematic fields
    missing_fields = [
        FRIENDLY_LABELS.get(f, f) 
        for f in MANDATORY_FIELDS 
        if f not in fields or not fields[f].get("value")
    ]
    
    low_conf_fields = [
        f"{FRIENDLY_LABELS.get(f, f)} ({fields[f].get('confidence', 0)*100:.0f}%)"
        for f in MANDATORY_FIELDS
        if f in fields and fields[f].get("confidence", 0) < 0.7
    ]
    
    # Build explanation
    summary_points = []
    
    # Check if validation caused status downgrade
    has_validation_issues = validation_result and not validation_result.get("valid")
    confidence_would_approve = conf >= approval_threshold
    
    if status == "Approved":
        summary_points.append(
            html.Li([
                html.Span(className="sap-icon sap-icon--success sap-icon--sm", style={"marginRight": "8px"}),
                "All key fields extracted with high confidence."
            ], className="sap-success")
        )
    else:
        # Check confidence first
        if confidence_would_approve and has_validation_issues:
            # High confidence but validation failed
            summary_points.append(
                html.Li([
                    html.Span(className="sap-icon sap-icon--warning sap-icon--sm", style={"marginRight": "8px"}),
                    f"Overall confidence ({conf*100:.0f}%) meets the {approval_threshold*100:.0f}% threshold. Status downgraded to 'Needs Review' due to business rule failures."
                ], className="sap-warning")
            )
        elif conf > review_threshold and conf < approval_threshold:
            # Moderate confidence
            summary_points.append(
                html.Li([
                    html.Span(className="sap-icon sap-icon--info sap-icon--sm", style={"marginRight": "8px"}),
                    f"Overall confidence ({conf*100:.0f}%) is between {review_threshold*100:.0f}% and {approval_threshold*100:.0f}% thresholds."
                ], className="sap-warning")
            )
        elif conf <= review_threshold:
            # Low confidence (at or below threshold)
            summary_points.append(
                html.Li([
                    html.Span(className="sap-icon sap-icon--error sap-icon--sm", style={"marginRight": "8px"}),
                    f"Overall confidence ({conf*100:.0f}%) is at or below {review_threshold*100:.0f}% threshold."
                ], className="sap-error")
            )
        
        # Add specific field issues
        if missing_fields:
            summary_points.append(
                html.Li([
                    html.Span(className="sap-icon sap-icon--error sap-icon--sm", style={"marginRight": "8px"}),
                    f"Missing critical fields: {', '.join(missing_fields)}"
                ], className="sap-error")
            )
        if low_conf_fields:
            summary_points.append(
                html.Li([
                    html.Span(className="sap-icon sap-icon--warning sap-icon--sm", style={"marginRight": "8px"}),
                    f"Low confidence fields (below 70%): {', '.join(low_conf_fields)}"
                ], className="sap-warning")
            )
    
    # Add validation results if present
    if validation_result:
        fields_validated = validation_result.get("fields_validated", 0)
        
        # Only show success message if fields were actually validated
        if validation_result.get("valid") and fields_validated > 0:
            summary_points.append(
                html.Li([
                    html.Span(className="sap-icon sap-icon--success sap-icon--sm", style={"marginRight": "8px"}),
                    "All business rule validations passed."
                ], className="sap-success")
            )
        elif not validation_result.get("valid"):
            violations = validation_result.get("violations", [])
            for violation in violations:
                summary_points.append(
                    html.Li(violation, className="sap-error")
                )
        
        warnings = validation_result.get("warnings", [])
        for warning in warnings:
            summary_points.append(
                html.Li(warning, className="sap-warning")
            )
    
    summary = html.Div([
        html.H4([
            html.Span(className="sap-icon sap-icon--report", style={"marginRight": "10px", "color": "var(--sap-brand-blue)"}),
            "Analysis Report"
        ], className="summary-title"),
        html.P(f"Document: {filename} | {num_pages} pages processed"),
        html.Ul(summary_points, className="summary-list")
    ])
    
    # ───────────────────────────────────────────────────────────────────────
    # PREPARE TABLE DATA
    # ───────────────────────────────────────────────────────────────────────
    df = pd.DataFrame(breakdown)
    
    # Mandatory fields table (subset)
    visible_df = df[df["Name"].isin(MANDATORY_FIELDS)]
    
    # Define table columns
    mandatory_columns = [
        {"name": i, "id": i} 
        for i in ["Field", "Extracted Value", "Confidence (%)", "Weight (%)", "Contribution (%)"]
    ]
    all_columns = [
        {"name": i, "id": i} 
        for i in ["Field", "Extracted Value", "Confidence (%)", "Weight (%)", "Contribution (%)"]
    ]
    
    # ───────────────────────────────────────────────────────────────────────
    # CONFIDENCE DISTRIBUTION CHART
    # ───────────────────────────────────────────────────────────────────────
    # Horizontal bar chart showing confidence for each field
    
    # Mark which fields are weighted (affect score)
    weighted_fields = set(CONFIG.get("field_weights", {}).keys())
    df["Subset"] = df["Name"].apply(
        lambda x: "Weighted Field" if x in weighted_fields else "Other Field"
    )
    
    # Create bar chart
    fig = px.bar(
        # Sort by Contribution (%) to show most influential fields first
        df.sort_values(by="Contribution (%)", ascending=True),
        y="Field",
        x="Confidence (%)",
        color="Subset",
        color_discrete_map={
            "Weighted Field": "#5B7F95",  # Muted blue - affects score
            "Other Field": "#BDBDBD"      # Grey - informational only
        },
        text="Confidence (%)",
        hover_data=["Field", "Extracted Value", "Confidence (%)", "Weight (%)", "Contribution (%)"],
        orientation='h',
        title=f"Field Confidence Distribution",
    )
    fig.update_traces(textposition='outside')
    fig.update_layout(
        xaxis_title="Confidence (%)",
        yaxis_title="",
        yaxis={'categoryorder': 'total ascending'},  # Sort by confidence
        legend_title="Field Group",
        margin=dict(l=200, r=20, t=50, b=40),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=max(400, 25 * len(df))  # Dynamic height based on field count
    )
    
    # ───────────────────────────────────────────────────────────────────────
    # RAW JSON OUTPUT
    # ───────────────────────────────────────────────────────────────────────
    json_str = json.dumps(raw_results, indent=2, ensure_ascii=False)
    
    # Return all updated components
    return (
        {"display": "none"},            # Hide welcome state
        {"display": "block"},           # Show results container
        verdict_text,
        verdict_style,
        {"display": "block"},           # Show gauge container when results ready
        gauge_fig,
        summary,
        visible_df.to_dict("records"),  # Mandatory fields table data
        mandatory_columns,
        df.to_dict("records"),          # All fields table data
        all_columns,
        fig,                            # Bar chart
        json_str                        # Raw JSON
    )

# ═══════════════════════════════════════════════════════════════════════════
# CUSTOM CSS STYLING
# ═══════════════════════════════════════════════════════════════════════════
# Custom HTML template with embedded CSS for professional appearance

dash_app.index_string = """
<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>UAE NOC Validator</title>
{%favicon%}
{%css%}
<link rel="stylesheet" href="/static/professional-ui.css">
<link rel="stylesheet" href="/static/sap-icons.css">
<link rel="stylesheet" href="/static/enhanced-ui.css">
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
<script src="/static/zoom-handler.js"></script>
</footer>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════════════════
# REST API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════
# These endpoints provide programmatic access to the application
# (useful for monitoring, integration, and health checks)

@server.route("/")
def home():
    """
    Root endpoint - API documentation
    
    Returns basic information and available endpoints.
    Useful for discovering API capabilities.
    
    Returns:
        JSON: Application info and endpoint list
    """
    return jsonify({
        "status": "running",
        "dashboard": "/dashboard/",
        "version": APP_VERSION,
        "description": "UAE NOC Validator API",
        "endpoints": {
            "dashboard": "/dashboard/",
            "health": "/health",
            "ready": "/ready",
            "metrics": "/metrics",
            "schema": "/api/schema",
            "jobs": "/api/jobs"
        }
    })

@server.route("/health")
def health():
    """
    Health check endpoint
    
    Used by Cloud Foundry and monitoring tools to check if app is alive.
    Always returns 200 OK if the server is running.
    
    Returns:
        JSON: Health status
    """
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": APP_VERSION
    })

@server.route("/ready")
def ready():
    """
    Readiness check endpoint
    
    Used by Cloud Foundry to check if app is ready to receive traffic.
    Verifies that all required components are initialized.
    
    Returns:
        JSON: Readiness status and checks
        HTTP 200: App is ready
        HTTP 503: App is not ready (service unavailable)
    """
    checks = {
        "config_valid": config_valid,              # SAP DOX configured?
        "schema_loaded": len(ALL_FIELDS) > 0,      # Schema loaded?
        "output_dir_exists": LOCAL_DIR.exists()    # Output directory created?
    }
    all_ready = all(checks.values())
    
    return jsonify({
        "ready": all_ready,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat()
    }), 200 if all_ready else 503

@server.route("/metrics")
def metrics():
    """
    Metrics endpoint for monitoring
    
    Provides statistics about processing jobs.
    Useful for monitoring application usage and performance.
    
    Returns:
        JSON: Job statistics
    """
    # Count jobs by status (thread-safe)
    with job_lock:
        total_jobs = len(processing_jobs)
        completed_jobs = sum(1 for j in processing_jobs.values() if j.status == "completed")
        failed_jobs = sum(1 for j in processing_jobs.values() if j.status == "failed")
        active_processing = sum(1 for j in processing_jobs.values() if j.status == "processing")
    
    return jsonify({
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "active_processing": active_processing,
        "timestamp": datetime.utcnow().isoformat()
    })

@server.route("/api/schema")
def get_schema_info():
    """
    Get loaded schema information
    
    Returns details about the currently loaded document schema.
    
    Returns:
        JSON: Schema metadata
    """
    return jsonify({
        "schema_name": SCHEMA_DATA.get("name", "Not loaded"),
        "total_fields": len(ALL_FIELDS),
        "mandatory_fields": MANDATORY_FIELDS,
        "field_count": len(SCHEMA_DATA.get("headerFields", []))
    })

@server.route("/api/jobs")
def get_jobs():
    """
    Get all processing jobs
    
    Returns list of all jobs (active and completed).
    Useful for monitoring and debugging.
    
    Returns:
        JSON: List of all jobs
    """
    with job_lock:
        jobs_list = [job.to_dict() for job in processing_jobs.values()]
    return jsonify({"jobs": jobs_list})

@server.route("/api/jobs/<job_id>")
def get_job(job_id):
    """
    Get specific job status
    
    Query a single job by its ID to check status and results.
    
    Args:
        job_id (str): Job UUID
        
    Returns:
        JSON: Job data or error if not found
    """
    with job_lock:
        job = processing_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(job.to_dict())

@server.route("/api/dox/documents")
def list_dox_documents():
    """
    List all documents in SAP DOX
    
    Retrieves up to 200 documents from SAP DOX service.
    Requires valid SAP DOX configuration.
    
    Returns:
        JSON: List of documents or error message
    """
    if not config_valid:
        return jsonify({"error": "SAP DOX not configured"}), 503
    
    try:
        # Get authentication token
        token = get_token()
        if not token:
            return jsonify({"error": "Failed to get authentication token"}), 500
        
        # Get client ID
        client_id = get_or_create_client(token)
        if not client_id:
            return jsonify({"error": "Failed to get client ID"}), 500
        
        # List documents
        headers = {"Authorization": f"Bearer {token}"}
        params = {"clientId": client_id}
        
        response = requests.get(
            f"{DOX_BASE_URL}/document/jobs",
            headers=headers,
            params=params,
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({
                "error": f"Failed to list documents: {response.status_code}",
                "details": response.text
            }), response.status_code
        
        return jsonify(response.json()), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@server.route("/api/dox/documents/delete-all", methods=["POST"])
def delete_all_dox_documents():
    """
    Delete all documents from SAP DOX
    
    This endpoint:
    1. Lists all documents in SAP DOX
    2. Extracts document IDs
    3. Sends bulk delete request
    
    ⚠️ WARNING: This operation cannot be undone!
    
    Returns:
        JSON: Deletion status and statistics
    """
    if not config_valid:
        return jsonify({"error": "SAP DOX not configured"}), 503
    
    try:
        print("🗑️ Starting document cleanup...")
        
        # Get authentication token
        token = get_token()
        if not token:
            print("❌ Failed to get authentication token")
            return jsonify({"error": "Failed to get authentication token"}), 500
        
        print("✔️ Token retrieved")
        
        # Get client ID
        client_id = get_or_create_client(token)
        if not client_id:
            print("❌ Failed to get client ID")
            return jsonify({"error": "Failed to get client ID"}), 500
        
        print(f"✔️ Client ID: {client_id}")
        
        # Step 1: List all documents
        headers = {"Authorization": f"Bearer {token}"}
        params = {"clientId": client_id}
        
        print(f"📡 Listing documents from: {DOX_BASE_URL}/document/jobs")
        list_response = requests.get(
            f"{DOX_BASE_URL}/document/jobs",
            headers=headers,
            params=params,
            timeout=30
        )
        
        print(f"📊 List response status: {list_response.status_code}")
        
        if list_response.status_code != 200:
            error_msg = f"Failed to list documents: {list_response.status_code}"
            print(f"❌ {error_msg}")
            print(f"Response: {list_response.text[:500]}")
            return jsonify({
                "error": error_msg,
                "details": list_response.text
            }), list_response.status_code
        
        # Step 2: Extract document IDs
        list_data = list_response.json()
        print(f"📋 List data structure: {json.dumps(list_data, indent=2)[:500]}")
        
        # Handle different response structures
        results = []
        if "results" in list_data:
            # Structure: {"results": [[{...}]]}
            results_data = list_data.get("results", [])
            if results_data and isinstance(results_data, list):
                if len(results_data) > 0 and isinstance(results_data[0], list):
                    results = results_data[0]
                else:
                    results = results_data
        elif "value" in list_data:
            # Alternative structure: {"value": [{...}]}
            results = list_data.get("value", [])
        
        print(f"📄 Found {len(results)} document(s)")
        
        if not results:
            print("ℹ️ No documents to delete")
            return jsonify({
                "status": "success",
                "message": "No documents to delete",
                "total_documents": 0,
                "deleted_documents": 0
            }), 200
        
        # Extract all document IDs
        document_ids = [doc.get("id") for doc in results if doc.get("id")]
        
        print(f"🔑 Extracted {len(document_ids)} document IDs: {document_ids}")
        
        if not document_ids:
            print("⚠️ No valid document IDs found")
            return jsonify({
                "status": "success",
                "message": "No valid document IDs found",
                "total_documents": len(results),
                "deleted_documents": 0
            }), 200
        
        # Step 3: Delete all documents using proper payload format
        delete_payload = {"value": document_ids}
        
        headers_with_content = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        delete_params = {"clientId": client_id}
        
        print(f"🗑️ Sending DELETE request to: {DOX_BASE_URL}/document/jobs")
        print(f"   Payload: {json.dumps(delete_payload)}")
        print(f"   Params: {delete_params}")
        
        delete_response = requests.delete(
            f"{DOX_BASE_URL}/document/jobs",
            headers=headers_with_content,
            params=delete_params,
            json=delete_payload,
            timeout=60
        )
        
        print(f"📊 Delete response status: {delete_response.status_code}")
        print(f"   Response body: {delete_response.text[:500]}")
        
        # Handle response
        if delete_response.status_code == 200:
            delete_data = delete_response.json()
            print(f"✔️ Successfully deleted {len(document_ids)} documents")
            return jsonify({
                "status": "success",
                "message": f"Successfully deleted {len(document_ids)} documents",
                "total_documents": len(results),
                "deleted_documents": len(document_ids),
                "document_ids": document_ids,
                "dox_response": delete_data
            }), 200
        else:
            print(f"⚠️ Delete returned non-200 status: {delete_response.status_code}")
            return jsonify({
                "status": "partial_failure",
                "message": f"Delete request returned status {delete_response.status_code}",
                "total_documents": len(results),
                "attempted_deletes": len(document_ids),
                "document_ids": document_ids,
                "error_details": delete_response.text
            }), delete_response.status_code
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Exception in delete_all_dox_documents: {e}")
        print(f"Traceback:\n{error_trace}")
        return jsonify({
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": error_trace
        }), 500

# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA CONFIGURATION TAB CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════

@dash_app.callback(
    Output("schema-fields-list", "children"),
    [Input("tab-schema", "n_clicks"),
     Input("schema-reset-btn", "n_clicks"),
     Input("custom-fields", "data")],
    prevent_initial_call=True
)
def load_schema_fields(tab_click, reset_click, custom_fields):
    """Load and display schema fields from the schema JSON file with mandatory badges and weights"""
    global SCHEMA_DATA, CONFIG
    
    ctx = callback_context
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
    
    # If reset button clicked, restore defaults
    if trigger_id == "schema-reset-btn":
        try:
            # Load default schema
            default_schema_path = os.path.join(os.path.dirname(__file__), "defaults", "schema_default.json")
            if os.path.exists(default_schema_path):
                with open(default_schema_path, "r") as f:
                    default_schema = json.load(f)
                SCHEMA_DATA.clear()
                SCHEMA_DATA.update(default_schema)
                # Save to active schema file
                with open(SCHEMA_FILE_PATH, "w") as f:
                    json.dump(SCHEMA_DATA, f, indent=2)
                print("Schema reset to defaults")
                
                # Clear the SAP DOX schema cache so schema will be re-created
                dox_schema_cache = os.path.join(os.path.dirname(__file__), "output", "dox_schema.json")
                if os.path.exists(dox_schema_cache):
                    os.remove(dox_schema_cache)
                    print("Cleared SAP DOX schema cache")
            
            # Load default config for field weights and mandatory fields
            default_config_path = os.path.join(os.path.dirname(__file__), "defaults", "config_default.json")
            if os.path.exists(default_config_path):
                with open(default_config_path, "r") as f:
                    default_config = json.load(f)
                # Only restore schema-related config (field_weights, mandatory_fields)
                CONFIG["field_weights"] = default_config.get("field_weights", {})
                CONFIG["mandatory_fields"] = default_config.get("mandatory_fields", [])
                with open("config.json", "w") as f:
                    json.dump(CONFIG, f, indent=2)
                print("Field weights and mandatory fields reset to defaults")
        except Exception as e:
            print(f"Error resetting schema: {e}")
    
    schema_fields = SCHEMA_DATA.get("headerFields", [])
    mandatory_fields = CONFIG.get("mandatory_fields", [])
    field_weights = CONFIG.get("field_weights", {})
    
    # Calculate total weight for percentage
    total_weight = sum(field_weights.values()) if field_weights else 1
    
    if not schema_fields:
        return html.Div([
            html.Span(className="sap-icon sap-icon--document sap-icon--xxl"),
            html.Div("No schema fields configured", className="history-empty-text"),
            html.Div("Add fields to configure extraction", className="history-empty-subtext"),
        ], className="empty-state")
    
    field_items = []
    for i, field in enumerate(schema_fields):
        field_name = field.get("name", f"field_{i}")
        field_desc = field.get("description", "No description")
        field_type = field.get("formattingType", "string")
        
        # Check if mandatory
        is_mandatory = field_name in mandatory_fields
        
        # Get weight and calculate percentage
        weight = field_weights.get(field_name, 0)
        weight_percentage = round((weight / total_weight) * 100, 1) if total_weight > 0 and weight > 0 else 0
        
        # Build badges
        badges = []
        if is_mandatory:
            badges.append(html.Span("Mandatory", className="badge-mandatory"))
        if weight > 0:
            badges.append(html.Span(f"{weight_percentage}%", className="badge-weight"))
        
        # Field type badge
        type_class = f"field-type-badge {field_type}"
        
        field_items.append(
            html.Div([
                html.Span(className="sap-icon sap-icon--drag field-drag-handle"),
                html.Div([
                    html.Div([
                        html.Span(FRIENDLY_LABELS.get(field_name, field_name)),
                    ], className="field-name"),
                    html.Div(field_desc, className="field-description"),
                ], className="field-info"),
                html.Div(badges, className="field-badges"),
                html.Span(field_type.upper(), className=type_class),
                html.Div([
                    html.Button(
                        html.Span(className="sap-icon sap-icon--edit sap-icon--sm"),
                        className="field-action-btn",
                        id={"type": "edit-field", "index": i}
                    ),
                    html.Button(
                        html.Span(className="sap-icon sap-icon--delete sap-icon--sm"),
                        className="field-action-btn delete",
                        id={"type": "remove-field", "index": i}
                    )
                ], className="field-actions")
            ], className="schema-field-card", id={"type": "schema-field", "index": i})
        )
    
    return field_items


# Callback to toggle Add Field modal
@dash_app.callback(
    Output("add-field-modal", "style"),
    [Input("add-schema-field-btn", "n_clicks"),
     Input("add-field-cancel", "n_clicks"),
     Input("add-field-confirm", "n_clicks")],
    prevent_initial_call=True
)
def toggle_add_field_modal(add_clicks, cancel_clicks, confirm_clicks):
    """Toggle the Add Field modal dialog"""
    ctx = callback_context
    if not ctx.triggered:
        return {"display": "none"}
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if trigger_id == "add-schema-field-btn":
        return {"display": "flex"}
    else:
        return {"display": "none"}


# Callback to download config JSON
@dash_app.callback(
    Output("download-config", "data"),
    Input("schema-download-btn", "n_clicks"),
    prevent_initial_call=True
)
def download_schema_config(n_clicks):
    """Generate and download the schema configuration as JSON"""
    if n_clicks:
        config_export = {
            "field_weights": CONFIG.get("field_weights", {}),
            "mandatory_fields": CONFIG.get("mandatory_fields", []),
            "schema_fields": SCHEMA_DATA.get("headerFields", []),
            "export_date": datetime.now().isoformat()
        }
        return dict(
            content=json.dumps(config_export, indent=2),
            filename="schema_config.json",
            type="application/json"
        )
    return None


# Callback to actually add a new schema field
@dash_app.callback(
    [Output("schema-fields-list", "children", allow_duplicate=True),
     Output("add-field-modal", "style", allow_duplicate=True),
     Output("new-field-name", "value"),
     Output("new-field-description", "value"),
     Output("new-field-weight", "value"),
     Output("new-field-mandatory", "value")],
    Input("add-field-confirm", "n_clicks"),
    [State("new-field-name", "value"),
     State("new-field-description", "value"),
     State("new-field-type", "value"),
     State("new-field-weight", "value"),
     State("new-field-mandatory", "value")],
    prevent_initial_call=True
)
def add_schema_field(n_clicks, field_name, description, field_type, weight, mandatory):
    """Add a new field to the schema configuration"""
    if not n_clicks or not field_name:
        raise PreventUpdate
    
    # Clean field name (convert to camelCase if needed)
    clean_name = field_name.strip().replace(" ", "")
    
    # Add to SCHEMA_DATA
    new_field = {
        "name": clean_name,
        "description": description or f"Field: {clean_name}",
        "formattingType": field_type or "string"
    }
    
    if "headerFields" not in SCHEMA_DATA:
        SCHEMA_DATA["headerFields"] = []
    
    # Check if field already exists
    existing_names = [f.get("name") for f in SCHEMA_DATA.get("headerFields", [])]
    if clean_name not in existing_names:
        SCHEMA_DATA["headerFields"].append(new_field)
    
    # Update CONFIG weights and mandatory
    if weight and weight > 0:
        CONFIG["field_weights"][clean_name] = weight
    
    if mandatory and "mandatory" in mandatory:
        if clean_name not in CONFIG.get("mandatory_fields", []):
            if "mandatory_fields" not in CONFIG:
                CONFIG["mandatory_fields"] = []
            CONFIG["mandatory_fields"].append(clean_name)
    
    # Save config
    try:
        with open("config.json", "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")
    
    # Regenerate the fields list
    schema_fields = SCHEMA_DATA.get("headerFields", [])
    mandatory_fields = CONFIG.get("mandatory_fields", [])
    field_weights = CONFIG.get("field_weights", {})
    total_weight = sum(field_weights.values()) if field_weights else 1
    
    field_items = []
    for i, field in enumerate(schema_fields):
        fname = field.get("name", f"field_{i}")
        fdesc = field.get("description", "No description")
        ftype = field.get("formattingType", "string")
        is_mandatory = fname in mandatory_fields
        w = field_weights.get(fname, 0)
        weight_pct = round((w / total_weight) * 100, 1) if total_weight > 0 and w > 0 else 0
        
        badges = []
        if is_mandatory:
            badges.append(html.Span("Mandatory", className="badge-mandatory"))
        if w > 0:
            badges.append(html.Span(f"{weight_pct}%", className="badge-weight"))
        
        field_items.append(
            html.Div([
                html.Span(className="sap-icon sap-icon--drag field-drag-handle"),
                html.Div([
                    html.Div([html.Span(FRIENDLY_LABELS.get(fname, fname))], className="field-name"),
                    html.Div(fdesc, className="field-description"),
                ], className="field-info"),
                html.Div(badges, className="field-badges"),
                html.Span(ftype.upper(), className=f"field-type-badge {ftype}"),
                html.Div([
                    html.Button(html.Span(className="sap-icon sap-icon--edit sap-icon--sm"), className="field-action-btn", id={"type": "edit-field", "index": i}),
                    html.Button(html.Span(className="sap-icon sap-icon--delete sap-icon--sm"), className="field-action-btn delete", id={"type": "remove-field", "index": i})
                ], className="field-actions")
            ], className="schema-field-card", id={"type": "schema-field", "index": i})
        )
    
    return field_items, {"display": "none"}, "", "", 5, []


# Callback to open Edit Field modal with pre-filled values
@dash_app.callback(
    [Output("edit-field-modal", "style"),
     Output("edit-field-index", "data"),
     Output("edit-field-name", "value"),
     Output("edit-field-description", "value"),
     Output("edit-field-type", "value"),
     Output("edit-field-weight", "value"),
     Output("edit-field-mandatory", "value")],
    [Input({"type": "edit-field", "index": ALL}, "n_clicks"),
     Input("edit-field-cancel", "n_clicks")],
    prevent_initial_call=True
)
def open_edit_field_modal(edit_clicks, cancel_clicks):
    """Open the edit field modal with pre-filled values"""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger = ctx.triggered[0]["prop_id"]
    
    if "edit-field-cancel" in trigger:
        return {"display": "none"}, None, "", "", "string", 0, []
    
    # Check if any edit button was clicked
    if not edit_clicks or not any(c for c in edit_clicks if c):
        raise PreventUpdate
    
    # Find which button was clicked
    import ast
    try:
        id_str = trigger.replace(".n_clicks", "")
        button_id = ast.literal_eval(id_str)
        field_index = button_id.get("index")
    except:
        raise PreventUpdate
    
    # Get field data
    schema_fields = SCHEMA_DATA.get("headerFields", [])
    if field_index >= len(schema_fields):
        raise PreventUpdate
    
    field = schema_fields[field_index]
    field_name = field.get("name", "")
    field_desc = field.get("description", "")
    field_type = field.get("formattingType", "string")
    
    # Get weight and mandatory status from CONFIG
    weight = CONFIG.get("field_weights", {}).get(field_name, 0)
    is_mandatory = field_name in CONFIG.get("mandatory_fields", [])
    mandatory_val = ["mandatory"] if is_mandatory else []
    
    return {"display": "flex"}, field_index, field_name, field_desc, field_type, weight, mandatory_val


# Callback to save edited field
@dash_app.callback(
    [Output("schema-fields-list", "children", allow_duplicate=True),
     Output("edit-field-modal", "style", allow_duplicate=True)],
    Input("edit-field-save", "n_clicks"),
    [State("edit-field-index", "data"),
     State("edit-field-name", "value"),
     State("edit-field-description", "value"),
     State("edit-field-type", "value"),
     State("edit-field-weight", "value"),
     State("edit-field-mandatory", "value")],
    prevent_initial_call=True
)
def save_edited_field(n_clicks, field_index, field_name, description, field_type, weight, mandatory):
    """Save the edited field"""
    if not n_clicks or field_index is None:
        raise PreventUpdate
    
    schema_fields = SCHEMA_DATA.get("headerFields", [])
    if field_index >= len(schema_fields):
        raise PreventUpdate
    
    # Update the field in SCHEMA_DATA
    SCHEMA_DATA["headerFields"][field_index]["description"] = description or ""
    SCHEMA_DATA["headerFields"][field_index]["formattingType"] = field_type or "string"
    
    # Update weight in CONFIG
    if weight is not None and weight > 0:
        CONFIG["field_weights"][field_name] = weight
    elif field_name in CONFIG.get("field_weights", {}):
        del CONFIG["field_weights"][field_name]
    
    # Update mandatory status
    mandatory_fields = CONFIG.get("mandatory_fields", [])
    if mandatory and "mandatory" in mandatory:
        if field_name not in mandatory_fields:
            CONFIG["mandatory_fields"].append(field_name)
    else:
        if field_name in mandatory_fields:
            CONFIG["mandatory_fields"].remove(field_name)
    
    # Save config
    try:
        with open("config.json", "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")
    
    # Regenerate the fields list
    field_weights = CONFIG.get("field_weights", {})
    total_weight = sum(field_weights.values()) if field_weights else 1
    
    field_items = []
    for i, field in enumerate(schema_fields):
        fname = field.get("name", f"field_{i}")
        fdesc = field.get("description", "No description")
        ftype = field.get("formattingType", "string")
        is_mand = fname in CONFIG.get("mandatory_fields", [])
        w = field_weights.get(fname, 0)
        weight_pct = round((w / total_weight) * 100, 1) if total_weight > 0 and w > 0 else 0
        
        badges = []
        if is_mand:
            badges.append(html.Span("Mandatory", className="badge-mandatory"))
        if w > 0:
            badges.append(html.Span(f"{weight_pct}%", className="badge-weight"))
        
        field_items.append(
            html.Div([
                html.Span(className="sap-icon sap-icon--drag field-drag-handle"),
                html.Div([
                    html.Div([html.Span(FRIENDLY_LABELS.get(fname, fname))], className="field-name"),
                    html.Div(fdesc, className="field-description"),
                ], className="field-info"),
                html.Div(badges, className="field-badges"),
                html.Span(ftype.upper(), className=f"field-type-badge {ftype}"),
                html.Div([
                    html.Button(html.Span(className="sap-icon sap-icon--edit sap-icon--sm"), className="field-action-btn", id={"type": "edit-field", "index": i}),
                    html.Button(html.Span(className="sap-icon sap-icon--delete sap-icon--sm"), className="field-action-btn delete", id={"type": "remove-field", "index": i})
                ], className="field-actions")
            ], className="schema-field-card", id={"type": "schema-field", "index": i})
        )
    
    return field_items, {"display": "none"}


# Callback to delete a schema field
@dash_app.callback(
    Output("schema-fields-list", "children", allow_duplicate=True),
    Input({"type": "remove-field", "index": ALL}, "n_clicks"),
    State({"type": "remove-field", "index": ALL}, "id"),
    prevent_initial_call=True
)
def delete_schema_field(n_clicks_list, ids):
    """Delete a schema field"""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    if not n_clicks_list or not any(c for c in n_clicks_list if c):
        raise PreventUpdate
    
    # Find which button was clicked
    triggered_id = ctx.triggered[0]["prop_id"]
    if triggered_id == ".":
        raise PreventUpdate
    
    import ast
    try:
        id_str = triggered_id.replace(".n_clicks", "")
        button_id = ast.literal_eval(id_str)
        field_index = button_id.get("index")
    except:
        raise PreventUpdate
    
    schema_fields = SCHEMA_DATA.get("headerFields", [])
    if field_index >= len(schema_fields):
        raise PreventUpdate
    
    # Get field name before removing
    field_name = schema_fields[field_index].get("name", "")
    
    # Remove from SCHEMA_DATA
    del SCHEMA_DATA["headerFields"][field_index]
    
    # Remove from CONFIG weights and mandatory
    if field_name in CONFIG.get("field_weights", {}):
        del CONFIG["field_weights"][field_name]
    if field_name in CONFIG.get("mandatory_fields", []):
        CONFIG["mandatory_fields"].remove(field_name)
    
    # Save config
    try:
        with open("config.json", "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")
    
    # Regenerate the fields list
    schema_fields = SCHEMA_DATA.get("headerFields", [])
    mandatory_fields = CONFIG.get("mandatory_fields", [])
    field_weights = CONFIG.get("field_weights", {})
    total_weight = sum(field_weights.values()) if field_weights else 1
    
    if not schema_fields:
        return html.Div([
            html.Span(className="sap-icon sap-icon--document sap-icon--xxl"),
            html.Div("No schema fields configured", className="history-empty-text"),
            html.Div("Add fields to configure extraction", className="history-empty-subtext"),
        ], className="empty-state")
    
    field_items = []
    for i, field in enumerate(schema_fields):
        fname = field.get("name", f"field_{i}")
        fdesc = field.get("description", "No description")
        ftype = field.get("formattingType", "string")
        is_mand = fname in mandatory_fields
        w = field_weights.get(fname, 0)
        weight_pct = round((w / total_weight) * 100, 1) if total_weight > 0 and w > 0 else 0
        
        badges = []
        if is_mand:
            badges.append(html.Span("Mandatory", className="badge-mandatory"))
        if w > 0:
            badges.append(html.Span(f"{weight_pct}%", className="badge-weight"))
        
        field_items.append(
            html.Div([
                html.Span(className="sap-icon sap-icon--drag field-drag-handle"),
                html.Div([
                    html.Div([html.Span(FRIENDLY_LABELS.get(fname, fname))], className="field-name"),
                    html.Div(fdesc, className="field-description"),
                ], className="field-info"),
                html.Div(badges, className="field-badges"),
                html.Span(ftype.upper(), className=f"field-type-badge {ftype}"),
                html.Div([
                    html.Button(html.Span(className="sap-icon sap-icon--edit sap-icon--sm"), className="field-action-btn", id={"type": "edit-field", "index": i}),
                    html.Button(html.Span(className="sap-icon sap-icon--delete sap-icon--sm"), className="field-action-btn delete", id={"type": "remove-field", "index": i})
                ], className="field-actions")
            ], className="schema-field-card", id={"type": "schema-field", "index": i})
        )
    
    return field_items


# ═══════════════════════════════════════════════════════════════════════════
# BUSINESS RULES TAB CALLBACKS  
# ═══════════════════════════════════════════════════════════════════════════

@dash_app.callback(
    Output("business-rules-list", "children"),
    [Input("tab-rules", "n_clicks"),
     Input("rules-reset-btn", "n_clicks")],
    prevent_initial_call=True
)
def load_business_rules(tab_click, reset_click):
    """Load and display business rules from config"""
    global CONFIG
    
    ctx = callback_context
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
    
    # If reset button clicked, restore default validation rules
    if trigger_id == "rules-reset-btn":
        try:
            default_config_path = os.path.join(os.path.dirname(__file__), "defaults", "config_default.json")
            if os.path.exists(default_config_path):
                with open(default_config_path, "r") as f:
                    default_config = json.load(f)
                # Only restore validation_rules
                CONFIG["validation_rules"] = default_config.get("validation_rules", {})
                with open("config.json", "w") as f:
                    json.dump(CONFIG, f, indent=2)
                print("Business rules reset to defaults")
        except Exception as e:
            print(f"Error resetting business rules: {e}")
    
    validation_rules = CONFIG.get("validation_rules", {})
    
    if not validation_rules:
        return html.Div([
            html.Span(className="sap-icon sap-icon--rules sap-icon--xxl"),
            html.Div("No business rules configured", className="history-empty-text"),
            html.Div("Add rules to enable validation", className="history-empty-subtext"),
        ], className="empty-state")
    
    rule_items = []
    for i, (field_name, rule) in enumerate(validation_rules.items()):
        rule_type = rule.get("type", "unknown")
        error_msg = rule.get("error_message", "Validation failed")
        
        # Create rule details based on type
        if rule_type == "date_age":
            max_months = rule.get("max_age_months", 6)
            details = f"Maximum age: {max_months} months"
        elif rule_type == "whitelist":
            allowed = rule.get("allowed_values", [])
            details = f"{len(allowed)} allowed values"
        else:
            details = "Custom rule"
        
        rule_items.append(
            html.Div([
                html.Div([
                    html.Div([
                        html.Span(className="sap-icon sap-icon--rules"),
                        html.Span(f"{FRIENDLY_LABELS.get(field_name, field_name)}", style={"marginLeft": "8px"})
                    ], className="rule-card-title"),
                    html.Div([
                        html.Span(rule_type.upper(), className=f"rule-type-badge {rule_type}"),
                        html.Button([
                            html.Span(className="sap-icon sap-icon--edit sap-icon--sm")
                        ], id={"type": "edit-rule-btn", "index": field_name}, className="rule-edit-btn", n_clicks=0, title="Edit Rule"),
                        html.Button([
                            html.Span(className="sap-icon sap-icon--delete sap-icon--sm")
                        ], id={"type": "delete-rule-btn", "index": field_name}, className="rule-delete-btn", n_clicks=0, title="Delete Rule"),
                    ], className="rule-card-actions"),
                ], className="rule-card-header"),
                html.Div([
                    html.Div([
                        html.Span("Rule Type:", className="rule-param-label"),
                        html.Span(rule_type.replace("_", " ").title(), className="rule-param-value"),
                    ], className="rule-param"),
                    html.Div([
                        html.Span("Details:", className="rule-param-label"),
                        html.Span(details, className="rule-param-value"),
                    ], className="rule-param"),
                    html.Div([
                        html.Span("Error Message:", className="rule-param-label"),
                        html.Span(error_msg, className="rule-param-value"),
                    ], className="rule-param"),
                ], className="rule-card-body"),
            ], className="rule-card")
        )
    
    return rule_items


# Callback to delete a rule
@dash_app.callback(
    Output("business-rules-list", "children", allow_duplicate=True),
    Input({"type": "delete-rule-btn", "index": ALL}, "n_clicks"),
    State({"type": "delete-rule-btn", "index": ALL}, "id"),
    prevent_initial_call=True
)
def delete_rule(n_clicks_list, ids):
    """Delete a business rule when the delete button is clicked"""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    # Check if any button was actually clicked (not just initialized)
    if not n_clicks_list or not any(click for click in n_clicks_list if click):
        raise PreventUpdate
    
    # Find which button was clicked
    triggered_id = ctx.triggered[0]["prop_id"]
    if triggered_id == ".":
        raise PreventUpdate
    
    # Parse the pattern-matching ID
    import ast
    try:
        id_str = triggered_id.replace(".n_clicks", "")
        button_id = ast.literal_eval(id_str)
        field_name = button_id.get("index")
    except:
        raise PreventUpdate
    
    if field_name and field_name in CONFIG.get("validation_rules", {}):
        del CONFIG["validation_rules"][field_name]
        # Save to config file
        try:
            with open("config.json", "w") as f:
                json.dump(CONFIG, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    # Regenerate rules list
    validation_rules = CONFIG.get("validation_rules", {})
    
    if not validation_rules:
        return html.Div([
            html.Span(className="sap-icon sap-icon--rules sap-icon--xxl"),
            html.Div("No business rules configured", className="history-empty-text"),
            html.Div("Add rules to enable validation", className="history-empty-subtext"),
        ], className="empty-state")
    
    rule_items = []
    for field_name_iter, rule in validation_rules.items():
        rule_type = rule.get("type", "unknown")
        error_msg = rule.get("error_message", "Validation failed")
        
        if rule_type == "date_age":
            max_months = rule.get("max_age_months", 6)
            details = f"Maximum age: {max_months} months"
        elif rule_type == "whitelist":
            allowed = rule.get("allowed_values", [])
            details = f"{len(allowed)} allowed values"
        else:
            details = "Custom rule"
        
        rule_items.append(
            html.Div([
                html.Div([
                    html.Div([
                        html.Span(className="sap-icon sap-icon--rules"),
                        html.Span(f"{FRIENDLY_LABELS.get(field_name_iter, field_name_iter)}", style={"marginLeft": "8px"})
                    ], className="rule-card-title"),
                    html.Div([
                        html.Span(rule_type.upper(), className=f"rule-type-badge {rule_type}"),
                        html.Button([
                            html.Span(className="sap-icon sap-icon--edit sap-icon--sm")
                        ], id={"type": "edit-rule-btn", "index": field_name_iter}, className="rule-edit-btn", n_clicks=0, title="Edit Rule"),
                        html.Button([
                            html.Span(className="sap-icon sap-icon--delete sap-icon--sm")
                        ], id={"type": "delete-rule-btn", "index": field_name_iter}, className="rule-delete-btn", n_clicks=0, title="Delete Rule"),
                    ], className="rule-card-actions"),
                ], className="rule-card-header"),
                html.Div([
                    html.Div([
                        html.Span("Rule Type:", className="rule-param-label"),
                        html.Span(rule_type.replace("_", " ").title(), className="rule-param-value"),
                    ], className="rule-param"),
                    html.Div([
                        html.Span("Details:", className="rule-param-label"),
                        html.Span(details, className="rule-param-value"),
                    ], className="rule-param"),
                    html.Div([
                        html.Span("Error Message:", className="rule-param-label"),
                        html.Span(error_msg, className="rule-param-value"),
                    ], className="rule-param"),
                ], className="rule-card-body"),
            ], className="rule-card")
        )
    
    return rule_items


# Callback to toggle Add Rule modal
@dash_app.callback(
    Output("add-rule-modal", "style"),
    [Input("add-rule-btn", "n_clicks"),
     Input("add-rule-cancel", "n_clicks"),
     Input("add-rule-confirm", "n_clicks")],
    prevent_initial_call=True
)
def toggle_add_rule_modal(add_clicks, cancel_clicks, confirm_clicks):
    """Toggle the Add Rule modal dialog"""
    ctx = callback_context
    if not ctx.triggered:
        return {"display": "none"}
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if trigger_id == "add-rule-btn":
        return {"display": "flex"}
    else:
        return {"display": "none"}


# Callback to show dynamic form fields based on rule type
@dash_app.callback(
    Output("rule-params-container", "children"),
    Input("new-rule-type", "value"),
    prevent_initial_call=True
)
def update_rule_params_form(rule_type):
    """Update the form fields based on selected rule type"""
    if rule_type == "date_age":
        return html.Div([
            html.Label("Maximum Age (Months)", className="form-label"),
            dcc.Input(id="new-rule-max-age", type="number", value=6, min=1, className="form-input"),
        ], className="form-group")
    elif rule_type == "whitelist":
        return html.Div([
            html.Label("Allowed Values (comma-separated)", className="form-label"),
            dcc.Input(id="new-rule-whitelist", type="text", placeholder="e.g., Value1, Value2, Value3", className="form-input"),
        ], className="form-group")
    else:
        return html.Div()


# Callback to download rules JSON
@dash_app.callback(
    Output("download-rules", "data"),
    Input("rules-download-btn", "n_clicks"),
    prevent_initial_call=True
)
def download_rules_config(n_clicks):
    """Generate and download the validation rules as JSON"""
    if n_clicks:
        rules_export = {
            "validation_rules": CONFIG.get("validation_rules", {}),
            "export_date": datetime.now().isoformat()
        }
        return dict(
            content=json.dumps(rules_export, indent=2),
            filename="validation_rules.json",
            type="application/json"
        )
    return None


# Callback to actually add a new business rule
@dash_app.callback(
    [Output("business-rules-list", "children", allow_duplicate=True),
     Output("add-rule-modal", "style", allow_duplicate=True),
     Output("new-rule-field", "value"),
     Output("new-rule-type", "value"),
     Output("new-rule-error", "value")],
    Input("add-rule-confirm", "n_clicks"),
    [State("new-rule-field", "value"),
     State("new-rule-type", "value"),
     State("new-rule-error", "value"),
     State("rule-params-container", "children")],
    prevent_initial_call=True
)
def add_business_rule(n_clicks, field_name, rule_type, error_msg, params_children):
    """Add a new business rule to config"""
    if not n_clicks or not field_name or not rule_type:
        raise PreventUpdate
    
    # Build the rule based on type
    new_rule = {
        "type": rule_type,
        "error_message": error_msg or f"Validation failed for {field_name}"
    }
    
    # Extract params based on rule type
    if rule_type == "date_age":
        new_rule["max_age_months"] = 6  # Default, would need to extract from params
    elif rule_type == "whitelist":
        new_rule["allowed_values"] = []  # Default empty list
    
    # Add to CONFIG
    if "validation_rules" not in CONFIG:
        CONFIG["validation_rules"] = {}
    CONFIG["validation_rules"][field_name] = new_rule
    
    # Save config
    try:
        with open("config.json", "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")
    
    # Regenerate rules list
    validation_rules = CONFIG.get("validation_rules", {})
    rule_items = []
    for fname, rule in validation_rules.items():
        rtype = rule.get("type", "unknown")
        err_msg = rule.get("error_message", "Validation failed")
        
        if rtype == "date_age":
            max_months = rule.get("max_age_months", 6)
            details = f"Maximum age: {max_months} months"
        elif rtype == "whitelist":
            allowed = rule.get("allowed_values", [])
            details = f"{len(allowed)} allowed values"
        else:
            details = "Custom rule"
        
        rule_items.append(
            html.Div([
                html.Div([
                    html.Div([
                        html.Span(className="sap-icon sap-icon--rules"),
                        html.Span(f"{FRIENDLY_LABELS.get(fname, fname)}", style={"marginLeft": "8px"})
                    ], className="rule-card-title"),
                    html.Div([
                        html.Span(rtype.upper(), className=f"rule-type-badge {rtype}"),
                        html.Button([html.Span(className="sap-icon sap-icon--edit sap-icon--sm")], id={"type": "edit-rule-btn", "index": fname}, className="rule-edit-btn", n_clicks=0, title="Edit Rule"),
                        html.Button([html.Span(className="sap-icon sap-icon--delete sap-icon--sm")], id={"type": "delete-rule-btn", "index": fname}, className="rule-delete-btn", n_clicks=0, title="Delete Rule"),
                    ], className="rule-card-actions"),
                ], className="rule-card-header"),
                html.Div([
                    html.Div([html.Span("Rule Type:", className="rule-param-label"), html.Span(rtype.replace("_", " ").title(), className="rule-param-value")], className="rule-param"),
                    html.Div([html.Span("Details:", className="rule-param-label"), html.Span(details, className="rule-param-value")], className="rule-param"),
                    html.Div([html.Span("Error Message:", className="rule-param-label"), html.Span(err_msg, className="rule-param-value")], className="rule-param"),
                ], className="rule-card-body"),
            ], className="rule-card")
        )
    
    return rule_items, {"display": "none"}, None, None, ""


# Callback to open Edit Rule modal with pre-filled values
@dash_app.callback(
    [Output("edit-rule-modal", "style"),
     Output("edit-rule-field-key", "data"),
     Output("edit-rule-field", "value"),
     Output("edit-rule-type", "value"),
     Output("edit-rule-error", "value"),
     Output("edit-rule-params-container", "children")],
    [Input({"type": "edit-rule-btn", "index": ALL}, "n_clicks"),
     Input("edit-rule-cancel", "n_clicks")],
    prevent_initial_call=True
)
def open_edit_rule_modal(edit_clicks, cancel_clicks):
    """Open the edit rule modal with pre-filled values"""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger = ctx.triggered[0]["prop_id"]
    
    if "edit-rule-cancel" in trigger:
        return {"display": "none"}, None, "", None, "", html.Div()
    
    # Check if any edit button was clicked
    if not edit_clicks or not any(c for c in edit_clicks if c):
        raise PreventUpdate
    
    # Find which button was clicked
    import ast
    try:
        id_str = trigger.replace(".n_clicks", "")
        button_id = ast.literal_eval(id_str)
        field_name = button_id.get("index")
    except:
        raise PreventUpdate
    
    # Get rule data from CONFIG
    rule = CONFIG.get("validation_rules", {}).get(field_name)
    if not rule:
        raise PreventUpdate
    
    rule_type = rule.get("type", "date_age")
    error_msg = rule.get("error_message", "")
    
    # Build params form based on rule type
    if rule_type == "date_age":
        max_months = rule.get("max_age_months", 6)
        params_form = html.Div([
            html.Label("Maximum Age (Months)", className="form-label"),
            dcc.Input(id="edit-rule-max-age", type="number", value=max_months, min=1, className="form-input"),
        ], className="form-group")
    elif rule_type == "whitelist":
        allowed = rule.get("allowed_values", [])
        params_form = html.Div([
            html.Label("Allowed Values (comma-separated)", className="form-label"),
            dcc.Input(id="edit-rule-whitelist", type="text", value=", ".join(allowed), className="form-input"),
        ], className="form-group")
    else:
        params_form = html.Div()
    
    return {"display": "flex"}, field_name, FRIENDLY_LABELS.get(field_name, field_name), rule_type, error_msg, params_form


# Callback to update edit rule params when type changes
@dash_app.callback(
    Output("edit-rule-params-container", "children", allow_duplicate=True),
    Input("edit-rule-type", "value"),
    State("edit-rule-field-key", "data"),
    prevent_initial_call=True
)
def update_edit_rule_params(rule_type, field_key):
    """Update edit rule params form when rule type changes"""
    if not rule_type:
        return html.Div()
    
    # Get current values from CONFIG if available
    current_rule = CONFIG.get("validation_rules", {}).get(field_key, {}) if field_key else {}
    
    if rule_type == "date_age":
        max_months = current_rule.get("max_age_months", 6)
        return html.Div([
            html.Label("Maximum Age (Months)", className="form-label"),
            dcc.Input(id="edit-rule-max-age", type="number", value=max_months, min=1, className="form-input"),
        ], className="form-group")
    elif rule_type == "whitelist":
        allowed = current_rule.get("allowed_values", [])
        return html.Div([
            html.Label("Allowed Values (comma-separated)", className="form-label"),
            dcc.Input(id="edit-rule-whitelist", type="text", value=", ".join(allowed) if allowed else "", className="form-input"),
        ], className="form-group")
    else:
        return html.Div()


# Callback to save edited rule
@dash_app.callback(
    [Output("business-rules-list", "children", allow_duplicate=True),
     Output("edit-rule-modal", "style", allow_duplicate=True)],
    Input("edit-rule-save", "n_clicks"),
    [State("edit-rule-field-key", "data"),
     State("edit-rule-type", "value"),
     State("edit-rule-error", "value"),
     State("edit-rule-params-container", "children")],
    prevent_initial_call=True
)
def save_edited_rule(n_clicks, field_key, rule_type, error_msg, params_children):
    """Save the edited rule"""
    if not n_clicks or not field_key:
        raise PreventUpdate
    
    # Get existing rule to preserve params if type hasn't changed
    existing_rule = CONFIG.get("validation_rules", {}).get(field_key, {})
    existing_type = existing_rule.get("type")
    
    # Build updated rule
    updated_rule = {
        "type": rule_type,
        "error_message": error_msg or f"Validation failed for {field_key}"
    }
    
    # Preserve existing params if same type, otherwise use defaults
    if rule_type == "date_age":
        if existing_type == "date_age":
            updated_rule["max_age_months"] = existing_rule.get("max_age_months", 6)
        else:
            updated_rule["max_age_months"] = 6
    elif rule_type == "whitelist":
        if existing_type == "whitelist":
            updated_rule["allowed_values"] = existing_rule.get("allowed_values", [])
        else:
            updated_rule["allowed_values"] = []
    
    # Update CONFIG
    CONFIG["validation_rules"][field_key] = updated_rule
    
    # Save config
    try:
        with open("config.json", "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")
    
    # Regenerate rules list
    validation_rules = CONFIG.get("validation_rules", {})
    rule_items = []
    for fname, rule in validation_rules.items():
        rtype = rule.get("type", "unknown")
        err_msg = rule.get("error_message", "Validation failed")
        
        if rtype == "date_age":
            max_months = rule.get("max_age_months", 6)
            details = f"Maximum age: {max_months} months"
        elif rtype == "whitelist":
            allowed = rule.get("allowed_values", [])
            details = f"{len(allowed)} allowed values"
        else:
            details = "Custom rule"
        
        rule_items.append(
            html.Div([
                html.Div([
                    html.Div([
                        html.Span(className="sap-icon sap-icon--rules"),
                        html.Span(f"{FRIENDLY_LABELS.get(fname, fname)}", style={"marginLeft": "8px"})
                    ], className="rule-card-title"),
                    html.Div([
                        html.Span(rtype.upper(), className=f"rule-type-badge {rtype}"),
                        html.Button([html.Span(className="sap-icon sap-icon--edit sap-icon--sm")], id={"type": "edit-rule-btn", "index": fname}, className="rule-edit-btn", n_clicks=0, title="Edit Rule"),
                        html.Button([html.Span(className="sap-icon sap-icon--delete sap-icon--sm")], id={"type": "delete-rule-btn", "index": fname}, className="rule-delete-btn", n_clicks=0, title="Delete Rule"),
                    ], className="rule-card-actions"),
                ], className="rule-card-header"),
                html.Div([
                    html.Div([html.Span("Rule Type:", className="rule-param-label"), html.Span(rtype.replace("_", " ").title(), className="rule-param-value")], className="rule-param"),
                    html.Div([html.Span("Details:", className="rule-param-label"), html.Span(details, className="rule-param-value")], className="rule-param"),
                    html.Div([html.Span("Error Message:", className="rule-param-label"), html.Span(err_msg, className="rule-param-value")], className="rule-param"),
                ], className="rule-card-body"),
            ], className="rule-card")
        )
    
    return rule_items, {"display": "none"}


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD TAB CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════

# Callback to handle status filter button clicks
@dash_app.callback(
    [Output("active-status-filter", "data"),
     Output("filter-all", "className"),
     Output("filter-approved", "className"),
     Output("filter-review", "className"),
     Output("filter-rejected", "className")],
    [Input("filter-all", "n_clicks"),
     Input("filter-approved", "n_clicks"),
     Input("filter-review", "n_clicks"),
     Input("filter-rejected", "n_clicks")],
    [State("active-status-filter", "data")],
    prevent_initial_call=True
)
def update_status_filter(all_clicks, approved_clicks, review_clicks, rejected_clicks, current_filter):
    """Update the active status filter when a filter button is clicked"""
    ctx = callback_context
    if not ctx.triggered:
        return current_filter, "filter-btn filter-btn--active", "filter-btn filter-btn--approved", "filter-btn filter-btn--review", "filter-btn filter-btn--rejected"
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    # Define base classes for each button
    base_classes = {
        "filter-all": "filter-btn",
        "filter-approved": "filter-btn filter-btn--approved",
        "filter-review": "filter-btn filter-btn--review",
        "filter-rejected": "filter-btn filter-btn--rejected"
    }
    
    # Determine active filter and update classes
    filter_map = {
        "filter-all": "all",
        "filter-approved": "Approved",
        "filter-review": "Needs Review",
        "filter-rejected": "Rejected"
    }
    
    active_filter = filter_map.get(trigger_id, "all")
    
    # Add active class to the clicked button
    classes = [
        base_classes["filter-all"] + (" filter-btn--active" if trigger_id == "filter-all" else ""),
        base_classes["filter-approved"] + (" filter-btn--active" if trigger_id == "filter-approved" else ""),
        base_classes["filter-review"] + (" filter-btn--active" if trigger_id == "filter-review" else ""),
        base_classes["filter-rejected"] + (" filter-btn--active" if trigger_id == "filter-rejected" else ""),
    ]
    
    return active_filter, classes[0], classes[1], classes[2], classes[3]


@dash_app.callback(
    [Output("metric-total", "children"),
     Output("metric-approved", "children"),
     Output("metric-review", "children"),
     Output("metric-rejected", "children"),
     Output("document-history-list", "children")],
    [Input("tab-dashboard", "n_clicks"),
     Input("job-result-store", "data"),
     Input("clear-history-btn", "n_clicks"),
     Input("history-search", "value"),
     Input("history-sort", "value"),
     Input("active-status-filter", "data")],
    [State("document-history", "data")],
    prevent_initial_call=True
)
def update_dashboard(tab_click, job_data, clear_click, search_text, sort_by, status_filter, history_data):
    """Update dashboard metrics and document history list with search/sort/filter"""
    ctx = callback_context
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None
    
    # Handle clear history
    if trigger_id == "clear-history-btn":
        return (
            "0", "0", "0", "0",
            html.Div([
                html.Span(className="sap-icon sap-icon--document sap-icon--xxl"),
                html.Div("No documents processed yet", className="history-empty-text"),
                html.Div("Upload a document to get started", className="history-empty-subtext"),
            ], className="history-empty")
        )
    
    # Calculate metrics from processing jobs
    with job_lock:
        completed_jobs = [j for j in processing_jobs.values() if j.status == "completed" and j.result]
    
    total = len(completed_jobs)
    approved = sum(1 for j in completed_jobs if j.result.get("status") == "Approved")
    review = sum(1 for j in completed_jobs if j.result.get("status") == "Needs Review")
    rejected = sum(1 for j in completed_jobs if j.result.get("status") == "Rejected")
    
    # Build history list
    if not completed_jobs:
        history_content = html.Div([
            html.Span(className="sap-icon sap-icon--document sap-icon--xxl"),
            html.Div("No documents processed yet", className="history-empty-text"),
            html.Div("Upload a document to get started", className="history-empty-subtext"),
        ], className="history-empty")
    else:
        # Apply status filter first
        filtered_jobs = completed_jobs
        if status_filter and status_filter != "all":
            filtered_jobs = [j for j in completed_jobs if j.result.get("status") == status_filter]
        
        # Apply search filter
        if search_text:
            search_lower = search_text.lower()
            filtered_jobs = [j for j in filtered_jobs if search_lower in j.result.get("filename", "").lower() or 
                             search_lower in j.result.get("status", "").lower()]
        
        # Apply sorting
        sort_by = sort_by or "date_desc"
        if sort_by == "date_desc":
            filtered_jobs = list(reversed(filtered_jobs))
        elif sort_by == "date_asc":
            pass  # Default order
        elif sort_by == "time_asc":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.result.get("processing_time", 0))
        elif sort_by == "time_desc":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.result.get("processing_time", 0), reverse=True)
        elif sort_by == "conf_desc":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.result.get("confidence", 0), reverse=True)
        elif sort_by == "conf_asc":
            filtered_jobs = sorted(filtered_jobs, key=lambda j: j.result.get("confidence", 0))
        elif sort_by == "status":
            status_order = {"Approved": 0, "Needs Review": 1, "Rejected": 2}
            filtered_jobs = sorted(filtered_jobs, key=lambda j: status_order.get(j.result.get("status", ""), 3))
        
        if not filtered_jobs:
            history_content = html.Div([
                html.Span(className="sap-icon sap-icon--search sap-icon--xxl"),
                html.Div("No documents match your search", className="history-empty-text"),
                html.Div("Try a different search term", className="history-empty-subtext"),
            ], className="history-empty")
        else:
            history_rows = []
            for job in filtered_jobs[:20]:  # Show up to 20 documents
                result = job.result
                filename = result.get("filename", "Unknown")
                status = result.get("status", "Unknown")
                confidence = result.get("confidence", 0)
                processing_time = result.get("processing_time", 0)
                num_pages = result.get("num_pages", 0)
                
                # Format processing date/time from job's created_at
                processed_date = job.created_at.strftime("%b %d, %Y %H:%M") if hasattr(job, 'created_at') else "Unknown"
                
                status_class = "doc-status " + status.lower().replace(" ", "-")
                
                history_rows.append(
                    html.Div([
                        html.Div([html.Span(className="sap-icon sap-icon--document")], className="doc-icon"),
                        html.Div([
                            html.Div(filename, className="doc-name", title=filename),
                            html.Div([
                                html.Span([
                                    html.Span(className="sap-icon sap-icon--calendar sap-icon--xs", style={"marginRight": "4px"}),
                                    processed_date
                                ], className="doc-meta-item"),
                                html.Span([
                                    html.Span(className="sap-icon sap-icon--time sap-icon--xs", style={"marginRight": "4px"}),
                                    f"{processing_time}s"
                                ], className="doc-meta-item"),
                                html.Span([
                                    html.Span(className="sap-icon sap-icon--pages sap-icon--xs", style={"marginRight": "4px"}),
                                    f"{num_pages} pages"
                                ], className="doc-meta-item") if num_pages > 0 else None,
                            ], className="doc-meta"),
                        ], className="doc-info"),
                        html.Span(status, className=status_class),
                        html.Span(f"{confidence*100:.0f}%", className="doc-confidence"),
                    ], className="document-row")
                )
            
            history_content = html.Div(history_rows)
    
    return (str(total), str(approved), str(review), str(rejected), history_content)


# ═══════════════════════════════════════════════════════════════════════════
# APPLICATION ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
# This block runs when the script is executed directly (not imported)

if __name__ == "__main__":
    """
    Start the application server
    
    Configuration:
        - host: 0.0.0.0 means accept connections from any network interface
                (required for Cloud Foundry deployment)
        - port: Default 7070, or PORT from environment (CF sets this automatically)
        - debug: Enable/disable debug mode (auto-reload, detailed errors)
        - threaded: Enable multi-threading (required for async processing)
    """
    
    # Print startup information
    print("═" * 80)
    print(f"🚀 UAE NOC Validator v{APP_VERSION}")
    print("═" * 80)
    print(f"📍 Dashboard: http://{APP_HOST}:{APP_PORT}/dashboard/")
    print(f"📋 Schema: {SCHEMA_DATA.get('name', 'Not loaded')}")
    print(f"🔧 Debug mode: {DEBUG_MODE}")
    print(f"✔️ Config valid: {config_valid}")
    print(f"📊 Fields tracked: {len(ALL_FIELDS)}")
    print(f"⚠️  Mandatory fields: {len(MANDATORY_FIELDS)}")
    print("═" * 80)
    
    # Start Flask server
    server.run(
        host=APP_HOST,
        port=APP_PORT,
        debug=DEBUG_MODE,
        threaded=True  # IMPORTANT: Required for async processing
    )
