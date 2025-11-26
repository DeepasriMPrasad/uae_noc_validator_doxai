# UAE NOC Validator - Production Ready

![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

AI-powered document validation system for UAE No Objection Certificates (NOC) using SAP Document Information Extraction service.

## 🚀 Features

- **Real-time Processing**: Async document processing with live progress updates
- **Intelligent Extraction**: AI-powered field extraction with confidence scoring
- **Production Ready**: Optimized for SAP BTP Cloud Foundry deployment
- **Comprehensive Logging**: Real-time logs and monitoring endpoints
- **Scalable Architecture**: Thread-based processing with job management
- **Security**: Optional XSUAA integration for authentication

## 📁 Project Structure

```
uae-noc-validator/
├── app.py                    # Main application (Flask + Dash)
├── config.json               # Application configuration
├── requirements.txt          # Python dependencies
├── manifest.yml              # Cloud Foundry manifest
├── mta.yaml                  # Multi-Target Application descriptor
├── xs-security.json          # XSUAA security configuration
├── Procfile                  # Process file for CF
├── runtime.txt               # Python version specification
├── .cfignore                 # CF deployment ignore file
├── .env.template             # Environment variables template
├── approuter/                # Application router (for auth)
│   ├── xs-app.json          # Router configuration
│   └── package.json         # Node.js dependencies
├── schemas/                  # DOX extraction schemas
│   └── uae_noc_schema_v2.json
├── output/                   # Runtime cache directory
└── static/                   # Static assets (optional)
```

## 🏃‍♂️ Quick Start (Local Development)

### Prerequisites

- Python 3.10+
- SAP Document Information Extraction service instance
- Service key with credentials

### 1. Clone and Setup

```bash
# Clone repository
git clone <repository-url>
cd uae-noc-validator

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy template
cp .env.template .env

# Edit with your SAP DOX credentials
nano .env  # or use your preferred editor
```

Required variables:
```env
UAA_URL=https://your-tenant.authentication.region.hana.ondemand.com/oauth/token
DOX_BASE_URL=https://aiservices-dox.cfapps.region.hana.ondemand.com/document-information-extraction/v1
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
```

### 3. Run Application

```bash
# Development mode
python app.py

# Production mode (with Gunicorn)
gunicorn --bind 0.0.0.0:7070 --workers 2 --threads 4 app:server
```

### 4. Access Dashboard

Open browser: http://localhost:7070/dashboard/

## ☁️ BTP Cloud Foundry Deployment

### Method 1: Simple CF Push

```bash
# Login to Cloud Foundry
cf login -a api.cf.<region>.hana.ondemand.com

# Set target org and space
cf target -o <your-org> -s <your-space>

# Push application
cf push

# Set environment variables
cf set-env uae-noc-validator UAA_URL "https://..."
cf set-env uae-noc-validator DOX_BASE_URL "https://..."
cf set-env uae-noc-validator CLIENT_ID "your-client-id"
cf set-env uae-noc-validator CLIENT_SECRET "your-client-secret"

# Restage to apply changes
cf restage uae-noc-validator
```

### Method 2: MTA Deployment (Recommended)

```bash
# Install MTA Build Tool
npm install -g mbt

# Build MTA archive
mbt build

# Deploy
cf deploy mta_archives/uae-noc-validator_2.0.0.mtar
```

### Method 3: With Service Binding

```bash
# Create DOX service instance
cf create-service document-information-extraction default uae-noc-dox

# Create service key
cf create-service-key uae-noc-dox uae-noc-key

# Get credentials
cf service-key uae-noc-dox uae-noc-key

# Deploy app
cf push

# Bind service
cf bind-service uae-noc-validator uae-noc-dox

# Restage
cf restage uae-noc-validator
```

## 🔒 Enable Authentication (Optional)

### 1. Deploy with XSUAA

```bash
# Create XSUAA service
cf create-service xsuaa application uae-noc-uaa -c xs-security.json

# Install approuter dependencies
cd approuter
npm install
cd ..

# Deploy both modules
cf push
```

### 2. Assign Role Collections

In SAP BTP Cockpit:
1. Navigate to Security → Role Collections
2. Find `UAE_NOC_Validator_User`
3. Assign to users who need access

## 📊 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Application info |
| `/dashboard/` | GET | Main dashboard UI |
| `/health` | GET | Health check (BTP monitoring) |
| `/ready` | GET | Readiness probe |
| `/metrics` | GET | Application metrics |
| `/api/schema` | GET | Schema information |
| `/api/jobs` | GET | List all processing jobs |
| `/api/jobs/<id>` | GET | Get specific job status |

## ⚙️ Configuration

### config.json Options

```json
{
  "approval_threshold": 0.85,     // Confidence threshold for approval
  "review_threshold": 0.6,         // Threshold for manual review
  "max_pages_per_chunk": 10,       // PDF chunk size
  "max_poll_attempts": 60,         // Max DOX polling attempts
  "poll_interval": 2,              // Seconds between polls
  "field_weights": {               // Custom field weights
    "applicationNumber": 0.2,
    "issuingAuthority": 0.2,
    // ...
  }
}
```

### Custom Schema

Place your DOX schema in `schemas/` directory:
- `uae_noc_schema_v2.json`
- `uae_noc_schema_custom_runtime_v2.json`

## 🔍 Monitoring

### Health Check
```bash
curl https://your-app.cfapps.region.hana.ondemand.com/health
```

### Readiness Check
```bash
curl https://your-app.cfapps.region.hana.ondemand.com/ready
```

### Metrics
```bash
curl https://your-app.cfapps.region.hana.ondemand.com/metrics
```

### View Logs
```bash
cf logs uae-noc-validator --recent
```

## 🛠️ Troubleshooting

### Common Issues

1. **App crashes on startup**
   - Check environment variables are set correctly
   - Verify SAP DOX credentials
   - Check logs: `cf logs uae-noc-validator --recent`

2. **Document processing fails**
   - Verify schema is uploaded to DOX
   - Check file size (max 50MB)
   - Ensure PDF is not corrupted

3. **Authentication issues**
   - Verify XSUAA service is bound
   - Check role collection assignments
   - Review approuter logs

4. **Slow performance**
   - Increase memory: `cf scale uae-noc-validator -m 1G`
   - Add more instances: `cf scale uae-noc-validator -i 2`

### Debug Mode

Set `DEBUG=true` in environment for detailed logs (not recommended for production).

## 📈 Performance Tuning

### Gunicorn Configuration

Adjust in `Procfile` or `manifest.yml`:
```bash
gunicorn --workers 4 --threads 8 --timeout 180 app:server
```

### Memory Allocation

In `manifest.yml`:
```yaml
memory: 1G
disk_quota: 2G
```

## 🔄 Updates & Maintenance

```bash
# Push new version with different name
cf push uae-noc-validator-new

# Map route to new version
cf map-route uae-noc-validator-new cfapps.region.hana.ondemand.com -n uae-noc-validator

# Unmap old route
cf unmap-route uae-noc-validator cfapps.region.hana.ondemand.com -n uae-noc-validator

# Delete old version
cf delete uae-noc-validator
```


