# UAE NOC Validator

## Overview

The UAE NOC Validator is an AI-powered document validation system designed to process and validate UAE No Objection Certificates (NOCs) using SAP Document Information Extraction (DOX) service. The application provides intelligent field extraction, confidence scoring, business rule validation, and an enterprise-grade web dashboard for document processing and results visualization.

**Key Capabilities:**
- Real-time PDF document processing with AI-powered field extraction
- Configurable confidence scoring with weighted field importance
- Business rule validation (date age, whitelist, etc.)
- Interactive web dashboard with SAP Fiori-inspired design
- Async job processing with progress tracking
- Comprehensive logging and monitoring

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture

**Framework:** Dash (Plotly) with Flask backend
- **UI Design:** SAP Fiori "Belize/Quartz" inspired theme with professional, flat design
- **Component Structure:** Tabbed interface with 4 main screens:
  - **Validator Tab:** Document upload, processing animation, and results display
  - **Schema Config Tab:** Field configuration with drag-drop interface
  - **Business Rules Tab:** Rule management with visual cards
  - **Dashboard Tab:** Metrics cards and document history
- **Icon System:** Custom SAP Fiori-style CSS icon classes (sap-icons.css) - no emojis in UI
- **Visualization:** Plotly charts for confidence scoring, data tables for extracted fields
- **Styling:** Three CSS files:
  - `professional-ui.css` - Base SAP Fiori styling
  - `enhanced-ui.css` - Tabbed navigation and configuration screens
  - `sap-icons.css` - Professional icon classes
- **Real-time Updates:** Callback-based reactive UI with interval components for progress tracking

**Design Rationale:** Dash provides a Python-native approach to building interactive web applications, eliminating the need for separate frontend/backend codebases. The SAP Fiori theme ensures enterprise-grade aesthetics suitable for business users and MD-level presentations.

**Recent Enhancements (Nov 2025):**
- 4-tab navigation system with state management via dcc.Store
- Professional processing animation with step-by-step progress indicators
- All user-facing emojis replaced with SAP Fiori-style icon classes
- SAP logo in header for enterprise branding
- Welcome state on initial load with feature cards (replaces blank graphs/tables)
- Collapsible sections with animated SAP arrow icons:
  - Processing Logs section
  - Document Preview section
  - View Document Extraction JSON section
- Schema Configuration screen with:
  - Mandatory field badges (orange "MANDATORY" tag)
  - Weight percentage display for each field
  - Add Field modal dialog with form inputs (field name, description, type, weight, mandatory checkbox)
  - Download Config button for exporting schema configuration as JSON
  - Edit and delete action buttons per field
  - Reset to Defaults functionality (with cache cleanup)
- Business Rules Configuration screen with:
  - Visual rule cards showing rule details
  - Add Rule modal dialog with dynamic form (rule type dropdown, conditional parameters)
  - Download Rules button for exporting validation rules as JSON
  - Reset to Defaults functionality
- Dashboard with:
  - Metrics cards (Total, Approved, Review, Rejected)
  - Document history list with clear all functionality
  - Search input for filtering documents
  - Sort dropdown (by date, processing time, confidence, status)

### Backend Architecture

**Core Framework:** Flask + Dash
- **Application Server:** Flask serving on port 7070 (configurable)
- **Processing Model:** Thread-based async processing with job queue system
- **Job Management:** In-memory job tracking with UUID-based job IDs
- **File Handling:** Base64 encoding for uploads, PyPDF2/PyMuPDF for PDF processing

**Document Processing Pipeline:**
1. PDF upload and validation
2. Authentication with SAP UAA (OAuth2)
3. Document upload to SAP DOX service
4. Polling for extraction results
5. Confidence calculation with weighted fields
6. Business rule validation
7. Results presentation with status determination

**Confidence Scoring System:**
- Weighted field scoring based on configurable field weights (config.json)
- Mandatory field checking with status downgrade on missing fields
- Three-tier status: Approved (>80%), Review (60-80%), Rejected (<60%)

**Business Rule Validation:**
- Pluggable validation system supporting multiple rule types
- Built-in validators: date_age (temporal validation), whitelist (enumeration validation)
- Extensible architecture for custom rule types
- Configuration-driven rule definitions

### Data Layer

**Configuration Management:**
- **config.json:** Application settings, field weights, mandatory fields, validation rules
- **Schema files:** JSON schema definitions for SAP DOX extraction (uae_noc_schema_custom_runtime_v9)
- **Environment variables:** Sensitive credentials via .env files (SAP UAA/DOX credentials)

**Data Storage:**
- **Runtime cache:** Local filesystem cache in `output/` directory
  - Client configuration (dox_client.json)
  - Schema configuration (dox_schema.json)
  - Processed document artifacts
- **No persistent database:** Stateless processing model with ephemeral job storage

**Schema Structure:**
- Header fields: applicationNumber, issuingAuthority, ownerName, issueDate, approvalUrl, etc.
- Line items: Support for structured data extraction from tables
- Metadata: Document type, version, validation state

### External Dependencies

**SAP Services:**
- **SAP UAA (User Account and Authentication):** OAuth2 token service for authentication
  - Endpoint: Configured via UAA_URL environment variable
  - Authentication: Client credentials flow (CLIENT_ID, CLIENT_SECRET)
  - Token management: Automatic token acquisition and refresh
  
- **SAP DOX (Document Information Extraction):** AI-powered document extraction service
  - Endpoint: Configured via DOX_BASE_URL environment variable
  - Operations: Client creation, schema management, document upload, extraction polling
  - Schema: Custom runtime schema for UAE NOC documents (v9)

**Python Libraries:**
- **Web Framework:** Flask 2.3.3, Dash 2.14.1+
- **Data Processing:** pandas 2.1.1+, plotly 5.17.0+
- **HTTP Client:** requests 2.31.0+
- **PDF Processing:** PyPDF2 3.0.1+, PyMuPDF 1.23.0+
- **Caching:** diskcache 5.6.3+ (for Dash background callbacks)
- **Date Parsing:** python-dateutil 2.8.2+ (for validation rules)
- **Environment:** python-dotenv 1.0.0+

**Deployment Targets:**
- **Cloud Foundry:** SAP BTP deployment via manifest.yml and mta.yaml
- **Local Development:** Direct Python execution or dev server mode
- **Application Router:** Optional XSUAA integration via Node.js approuter for authentication

**Authentication Options:**
- **Open Access Mode:** Direct application access without authentication
- **XSUAA Mode:** SAP BTP authentication via approuter with xs-security.json configuration

**Notable Design Decisions:**
- **No traditional database:** Stateless architecture reduces operational complexity, suitable for document processing workloads
- **Thread-based processing:** Simpler than async/await for I/O-bound SAP API calls, adequate for expected load
- **Configuration-driven:** Field weights, mandatory fields, and validation rules externalized to config.json for business user customization
- **Modular validation:** Rule-based validation system allows adding new business rules without code changes