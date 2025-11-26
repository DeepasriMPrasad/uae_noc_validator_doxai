# UAE NOC Validator - Architecture & Flow Diagrams

## Table of Contents
1. [System Architecture](#system-architecture)
2. [Sequence Diagrams](#sequence-diagrams)
3. [Activity Diagrams](#activity-diagrams)
4. [Data Flow](#data-flow)

---

## System Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        Browser[Web Browser]
        User[End User]
    end
    
    subgraph "Application Layer"
        Flask[Flask Server<br/>Port 7070]
        Dash[Dash Dashboard<br/>UI Components]
        AppLogic[Application Logic<br/>- PDF Processing<br/>- Confidence Calculation]
    end
    
    subgraph "External Services"
        SAPUAA[SAP UAA<br/>OAuth2 Token Service]
        SAPDOX[SAP DOX Service<br/>Document Extraction API]
    end
    
    subgraph "Data Layer"
        EnvFile[.env File<br/>Configuration]
        Schema[JSON Schema<br/>Field Definitions]
        Cache[Local Cache<br/>Client Config]
    end
    
    User -->|Uploads PDF| Browser
    Browser -->|HTTP Request| Flask
    Flask -->|Renders UI| Dash
    Dash -->|User Interactions| Flask
    Flask -->|Processes Data| AppLogic
    AppLogic -->|Reads Config| EnvFile
    AppLogic -->|Loads Schema| Schema
    AppLogic -->|Caches Data| Cache
    AppLogic -->|Auth Request| SAPUAA
    SAPUAA -->|Access Token| AppLogic
    AppLogic -->|Upload Document| SAPDOX
    SAPDOX -->|Extraction Results| AppLogic
    AppLogic -->|Results| Dash
    Dash -->|Displays Results| Browser
    Browser -->|Views Results| User
```

---

## Sequence Diagrams

### 1. Complete Document Upload and Validation Flow

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant Dash
    participant Flask
    participant AppLogic
    participant EnvConfig
    participant SAP_UAA
    participant SAP_DOX
    participant PDFProcessor
    participant ConfidenceEngine
    
    User->>Browser: Select PDF Document
    Browser->>Dash: Upload File (Base64)
    Dash->>Flask: HTTP POST /dashboard/_dash-update-component
    Flask->>AppLogic: handle_upload(content, filename)
    
    Note over AppLogic: Initialization Phase
    AppLogic->>EnvConfig: Load environment variables
    EnvConfig-->>AppLogic: UAA_URL, DOX_BASE_URL, CLIENT_ID, CLIENT_SECRET
    
    Note over AppLogic: PDF Processing Phase
    AppLogic->>PDFProcessor: Decode Base64 content
    PDFProcessor->>PDFProcessor: Check PDF page count
    
    alt PDF has > 10 pages
        PDFProcessor->>PDFProcessor: Split into chunks of 10 pages
        PDFProcessor-->>AppLogic: List of PDF chunks
    else PDF has ≤ 10 pages
        PDFProcessor-->>AppLogic: Single PDF chunk
    end
    
    Note over AppLogic: Authentication Phase
    AppLogic->>SAP_UAA: POST /oauth/token<br/>(grant_type=client_credentials)
    SAP_UAA-->>AppLogic: Access Token (JWT)
    
    Note over AppLogic: Client Setup Phase
    AppLogic->>SAP_DOX: Check existing DOX client
    alt Client exists in cache
        AppLogic->>AppLogic: Use cached client ID
    else No cached client
        AppLogic->>SAP_DOX: GET /clients (limit=10)
        alt Existing client found
            SAP_DOX-->>AppLogic: Existing client list
            AppLogic->>AppLogic: Cache first client ID
        else No clients found
            AppLogic->>SAP_DOX: POST /clients<br/>(clientId=uae_noc_client)
            SAP_DOX-->>AppLogic: New client created
            AppLogic->>AppLogic: Cache new client ID
        end
    end
    
    Note over AppLogic: Document Upload & Processing Loop
    loop For each PDF chunk
        AppLogic->>SAP_DOX: POST /document/jobs<br/>(file, clientId, schema)
        SAP_DOX-->>AppLogic: Job ID
        
        Note over AppLogic: Polling Phase (max 60 attempts)
        loop Every 2 seconds (max 60 times)
            AppLogic->>SAP_DOX: GET /document/jobs/{jobId}
            SAP_DOX-->>AppLogic: Job Status
            
            alt Status = DONE
                AppLogic->>AppLogic: Break polling loop
            else Status = FAILED/ERROR
                SAP_DOX-->>AppLogic: Error details
                AppLogic-->>Dash: Error response
                Dash-->>Browser: Display error
                Browser-->>User: Show error message
            end
        end
        
        Note over AppLogic: Extraction Phase
        AppLogic->>SAP_DOX: GET /document/jobs/{jobId}?extractedValues=true
        SAP_DOX-->>AppLogic: Extracted field data
        AppLogic->>AppLogic: Merge chunk results
    end
    
    Note over AppLogic: Confidence Calculation Phase
    AppLogic->>ConfidenceEngine: compute_confidence(fields, use_approximation)
    ConfidenceEngine->>ConfidenceEngine: Calculate weighted confidence
    
    alt Approximation enabled
        ConfidenceEngine->>ConfidenceEngine: Check mandatory fields
        alt All mandatory fields present & ≥70% confidence
            ConfidenceEngine->>ConfidenceEngine: Set confidence = 100%
        else Missing mandatory fields
            ConfidenceEngine->>ConfidenceEngine: Set confidence = 0%
        end
    end
    
    ConfidenceEngine->>ConfidenceEngine: Determine status (Approved/Needs Review/Rejected)
    ConfidenceEngine->>ConfidenceEngine: Generate breakdown table
    ConfidenceEngine->>ConfidenceEngine: Create visualization chart
    ConfidenceEngine-->>AppLogic: Confidence results
    
    Note over AppLogic: Response Generation Phase
    AppLogic->>AppLogic: Format response data
    AppLogic-->>Flask: Results (status, confidence, breakdown, charts)
    Flask-->>Dash: Render results
    Dash-->>Browser: Update UI components
    Browser-->>User: Display validation results
```

### 2. Authentication Flow

```mermaid
sequenceDiagram
    participant AppLogic
    participant EnvConfig
    participant SAP_UAA
    participant Cache
    
    Note over AppLogic: Token Request Phase
    AppLogic->>EnvConfig: Read UAA_URL, CLIENT_ID, CLIENT_SECRET
    EnvConfig-->>AppLogic: Configuration values
    
    AppLogic->>SAP_UAA: POST /oauth/token
    Note right of SAP_UAA: Headers:<br/>grant_type=client_credentials<br/>Auth: Basic(CLIENT_ID:CLIENT_SECRET)
    
    alt Authentication Success
        SAP_UAA-->>AppLogic: 200 OK<br/>{access_token, expires_in, token_type}
        AppLogic->>AppLogic: Extract access_token
        Note over AppLogic: Token stored in memory<br/>for subsequent requests
    else Authentication Failed
        SAP_UAA-->>AppLogic: 401 Unauthorized
        AppLogic->>AppLogic: Log error
        AppLogic-->>AppLogic: Return None
    end
```

### 3. DOX Client Management Flow

```mermaid
sequenceDiagram
    participant AppLogic
    participant LocalCache
    participant SAP_DOX
    
    AppLogic->>LocalCache: Check for dox_client.json
    
    alt Client cached
        LocalCache-->>AppLogic: Cached client ID
        Note over AppLogic: Use cached client,<br/>skip API calls
    else No cached client
        AppLogic->>SAP_DOX: GET /clients?limit=10
        
        alt Clients exist
            SAP_DOX-->>AppLogic: List of existing clients
            AppLogic->>AppLogic: Select first client
            AppLogic->>LocalCache: Cache client ID
        else No clients found
            AppLogic->>SAP_DOX: POST /clients<br/>{clientId: "uae_noc_client"}
            
            alt Creation successful
                SAP_DOX-->>AppLogic: 200/201 Created<br/>New client details
                AppLogic->>LocalCache: Cache new client ID
            else Creation failed
                SAP_DOX-->>AppLogic: Error response
                AppLogic-->>AppLogic: Return None
            end
        end
    end
```

### 4. PDF Processing Flow

```mermaid
sequenceDiagram
    participant AppLogic
    participant PDFReader
    participant PDFWriter
    participant ChunkProcessor
    
    AppLogic->>AppLogic: Decode Base64 PDF content
    AppLogic->>PDFReader: Create PdfReader(BytesIO(file_bytes))
    PDFReader-->>AppLogic: PDF Reader instance
    
    AppLogic->>PDFReader: Get number of pages
    PDFReader-->>AppLogic: Page count
    
    alt Pages > 10
        Note over AppLogic: Split into chunks
        AppLogic->>ChunkProcessor: Initialize chunk list
        
        loop For every 10 pages
            ChunkProcessor->>PDFWriter: Create new PdfWriter()
            loop Add pages to chunk
                ChunkProcessor->>PDFReader: Get page[i]
                PDFReader-->>ChunkProcessor: Page object
                ChunkProcessor->>PDFWriter: Add page to writer
            end
            ChunkProcessor->>PDFWriter: Write to BytesIO
            PDFWriter-->>ChunkProcessor: PDF chunk bytes
            ChunkProcessor->>ChunkProcessor: Add to chunk list
        end
        
        ChunkProcessor-->>AppLogic: List of PDF chunks
    else Pages ≤ 10
        Note over AppLogic: Process as single chunk
        AppLogic-->>AppLogic: Single chunk = original file
    end
    
    AppLogic->>AppLogic: Process each chunk sequentially
```

---

## Activity Diagrams

### 1. Complete Application Workflow

```mermaid
flowchart TD
    Start([User Opens Dashboard]) --> UploadPDF[User Selects PDF]
    UploadPDF --> ValidateFile{File Valid?}
    
    ValidateFile -->|No| ShowError1[Display Error Message]
    ShowError1 --> End([End])
    
    ValidateFile -->|Yes| LoadEnv[Load Environment Variables]
    LoadEnv --> CheckEnv{All Config<br/>Present?}
    
    CheckEnv -->|No| ShowError2[Display Configuration Error]
    ShowError2 --> End
    
    CheckEnv -->|Yes| DecodePDF[Decode Base64 PDF]
    DecodePDF --> CheckPages{Pages > 10?}
    
    CheckPages -->|Yes| SplitPDF[Split into 10-page Chunks]
    CheckPages -->|No| SingleChunk[Process as Single Chunk]
    
    SplitPDF --> GetToken
    SingleChunk --> GetToken[Get OAuth Token from SAP UAA]
    
    GetToken --> TokenValid{Token<br/>Obtained?}
    TokenValid -->|No| ShowError3[Display Auth Error]
    ShowError3 --> End
    
    TokenValid -->|Yes| GetClient[Get/Create DOX Client]
    GetClient --> ClientValid{Client ID<br/>Obtained?}
    
    ClientValid -->|No| ShowError4[Display Client Error]
    ShowError4 --> End
    
    ClientValid -->|Yes| ProcessChunks[Start Processing Chunks]
    
    ProcessChunks --> LoopChunks{More Chunks<br/>to Process?}
    
    LoopChunks -->|Yes| UploadChunk[Upload Chunk to SAP DOX]
    UploadChunk --> GetJobID[Receive Job ID]
    GetJobID --> PollStatus[Poll Job Status]
    
    PollStatus --> CheckStatus{Job Status?}
    CheckStatus -->|DONE| FetchExtraction[Fetch Extracted Data]
    CheckStatus -->|FAILED/ERROR| ShowError5[Display Processing Error]
    CheckStatus -->|PENDING| Wait[Wait 2 seconds]
    
    Wait --> CheckAttempts{Max Attempts<br/>Reached?}
    CheckAttempts -->|No| PollStatus
    CheckAttempts -->|Yes| ShowError6[Display Timeout Error]
    
    ShowError5 --> End
    ShowError6 --> End
    
    FetchExtraction --> MergeResults[Merge with Previous Results]
    MergeResults --> LoopChunks
    
    LoopChunks -->|No| CalcConfidence[Calculate Confidence Scores]
    
    CalcConfidence --> CheckApprox{Approximation<br/>Enabled?}
    
    CheckApprox -->|Yes| CheckMandatory{All Mandatory<br/>Fields Present?}
    CheckMandatory -->|Yes & ≥70%| SetConf100[Set Confidence = 100%]
    CheckMandatory -->|No| SetConf0[Set Confidence = 0%]
    
    CheckApprox -->|No| WeightedCalc[Weighted Confidence Calculation]
    
    SetConf100 --> DetermineStatus
    SetConf0 --> DetermineStatus
    WeightedCalc --> DetermineStatus{Confidence<br/>Threshold?}
    
    DetermineStatus -->|≥85%| StatusApproved[Status = Approved]
    DetermineStatus -->|60-84%| StatusReview[Status = Needs Review]
    DetermineStatus -->|<60%| StatusRejected[Status = Rejected]
    
    StatusApproved --> GenerateViz
    StatusReview --> GenerateViz
    StatusRejected --> GenerateViz[Generate Visualizations]
    
    GenerateViz --> CreateTables[Create Breakdown Tables]
    CreateTables --> CreateChart[Create Confidence Chart]
    CreateChart --> FormatJSON[Format Raw JSON]
    FormatJSON --> DisplayResults[Display All Results to User]
    
    DisplayResults --> End
```

### 2. Confidence Calculation Workflow

```mermaid
flowchart TD
    Start([Start Confidence Calculation]) --> InitVars[Initialize Variables:<br/>- total_conf = 0<br/>- breakdown = []]
    
    InitVars --> LoadFields[Load ALL_FIELDS from Schema]
    LoadFields --> DefineWeights[Define Weighted Subset:<br/>- applicationNumber: 20%<br/>- issuingAuthority: 20%<br/>- ownerName: 20%<br/>- issueDate: 20%<br/>- documentStatus: 20%]
    
    DefineWeights --> LoopFields{For Each<br/>Field}
    
    LoopFields -->|Next Field| GetFieldData[Get Field Data from Extraction]
    GetFieldData --> ExtractConf[Extract Confidence Value]
    ExtractConf --> ExtractValue[Extract Field Value]
    
    ExtractValue --> CheckWeighted{Field in<br/>Weighted Subset?}
    
    CheckWeighted -->|Yes| CalcContrib[Calculate:<br/>contribution = confidence × weight]
    CalcContrib --> AddToTotal[total_conf += contribution]
    AddToTotal --> SetColorGreen[Row Color = Light Green]
    
    CheckWeighted -->|No| ZeroContrib[contribution = 0]
    ZeroContrib --> SetColorGrey[Row Color = Light Grey]
    
    SetColorGreen --> AddBreakdown
    SetColorGrey --> AddBreakdown[Add to Breakdown Array]
    
    AddBreakdown --> LoopFields
    
    LoopFields -->|All Done| CheckApprox{Approximation<br/>Mode Enabled?}
    
    CheckApprox -->|No| RoundConf[Round total_conf to 3 decimals]
    RoundConf --> ReturnResults
    
    CheckApprox -->|Yes| CheckMandatory[Check ALL Mandatory Fields]
    CheckMandatory --> AllPresent{All Present?}
    
    AllPresent -->|No| SetZero[Set total_conf = 0%]
    SetZero --> ReturnResults
    
    AllPresent -->|Yes| CheckConfidence{All ≥70%<br/>Confidence?}
    
    CheckConfidence -->|Yes| SetHundred[Set total_conf = 100%]
    CheckConfidence -->|No| KeepCalc[Keep Calculated Confidence]
    
    SetHundred --> ReturnResults
    KeepCalc --> ReturnResults[Return: total_conf, breakdown]
    
    ReturnResults --> End([End])
```

### 3. Error Handling Workflow

```mermaid
flowchart TD
    Start([Error Occurs]) --> IdentifyError{Error Type?}
    
    IdentifyError -->|Token Fetch Failed| LogToken[Log: Token fetch failed]
    LogToken --> ReturnError1[Return: error='Token retrieval failed', code=500]
    
    IdentifyError -->|Client ID Failed| LogClient[Log: Client ID retrieval failed]
    LogClient --> ReturnError2[Return: error='Client ID retrieval failed', code=500]
    
    IdentifyError -->|Upload Failed| LogUpload[Log: Upload failed with status code]
    LogUpload --> ReturnError3[Return: error=response.text, code=status_code]
    
    IdentifyError -->|Job ID Missing| LogJobID[Log: Job ID missing in response]
    LogJobID --> ReturnError4[Return: error='Job ID missing', code=500]
    
    IdentifyError -->|Processing Failed| LogProcess[Log: Processing failed]
    LogProcess --> ReturnError5[Return: error='Processing failed', details, code=500]
    
    IdentifyError -->|Timeout| LogTimeout[Log: Timeout after 60 attempts]
    LogTimeout --> ReturnError6[Return: error='Timeout waiting for completion', code=504]
    
    IdentifyError -->|Fetch Failed| LogFetch[Log: Fetch failed with status]
    LogFetch --> ReturnError7[Return: error=response.text, code=status_code]
    
    IdentifyError -->|Quota Exceeded| LogQuota[Log: API quota exceeded]
    LogQuota --> ReturnError8[Return: error='Quota exceeded', code=429]
    
    ReturnError1 --> UpdateUI
    ReturnError2 --> UpdateUI
    ReturnError3 --> UpdateUI
    ReturnError4 --> UpdateUI
    ReturnError5 --> UpdateUI
    ReturnError6 --> UpdateUI
    ReturnError7 --> UpdateUI
    ReturnError8 --> UpdateUI[Update UI with Error Message]
    
    UpdateUI --> LogBuffer[Add to Log Buffer]
    LogBuffer --> DisplayLog[Display in Process Logs Panel]
    DisplayLog --> End([User Sees Error])
```

### 4. Startup and Configuration Flow

```mermaid
flowchart TD
    Start([Application Startup]) --> LoadDotenv[Load .env File]
    LoadDotenv --> ReadEnv[Read Environment Variables]
    
    ReadEnv --> CheckVars{All Required<br/>Variables Present?}
    
    CheckVars -->|No| RaiseError[Raise ValueError:<br/>'Missing required environment variables']
    RaiseError --> AppFails([Application Fails to Start])
    
    CheckVars -->|Yes| SetConfig[Set Configuration:<br/>- UAA_URL<br/>- DOX_BASE_URL<br/>- CLIENT_ID<br/>- CLIENT_SECRET]
    
    SetConfig --> CreateDirs[Create Output Directory]
    CreateDirs --> LoadSchema[Load JSON Schema File]
    
    LoadSchema --> SchemaExists{Schema File<br/>Exists?}
    
    SchemaExists -->|Yes| ParseSchema[Parse Schema JSON]
    ParseSchema --> ExtractFields[Extract:<br/>- Header Fields<br/>- Mandatory Fields<br/>- Friendly Labels]
    ExtractFields --> SchemaSuccess[Log: Schema loaded successfully]
    
    SchemaExists -->|No| UseDefaults[Use Default Configuration]
    UseDefaults --> LogWarning[Log: Using fallback configuration]
    
    SchemaSuccess --> InitFlask
    LogWarning --> InitFlask[Initialize Flask Server]
    
    InitFlask --> InitDash[Initialize Dash Application]
    InitDash --> RegisterCallbacks[Register Dash Callbacks]
    RegisterCallbacks --> StartServer[Start Flask Server on Port 7070]
    
    StartServer --> ReadyServe([Ready to Serve Requests])
```

---

## Data Flow

### 1. Data Transformation Pipeline

```mermaid
flowchart LR
    subgraph Input
        PDF[PDF Document<br/>Binary]
    end
    
    subgraph Processing
        Base64[Base64 Encoded<br/>String]
        Chunks[PDF Chunks<br/>≤10 pages each]
        Jobs[DOX Job IDs<br/>per Chunk]
        Raw[Raw Extraction<br/>JSON]
    end
    
    subgraph Analysis
        Fields[Structured Fields<br/>with Confidence]
        Weighted[Weighted Confidence<br/>Calculation]
        Status[Final Status<br/>Determination]
    end
    
    subgraph Output
        Tables[Breakdown Tables<br/>HTML/DataFrames]
        Chart[Confidence Chart<br/>Plotly Visualization]
        JSON[Raw JSON<br/>Display]
        Banner[Status Banner<br/>Color-coded]
    end
    
    PDF -->|Upload| Base64
    Base64 -->|Decode & Split| Chunks
    Chunks -->|Upload to DOX| Jobs
    Jobs -->|Poll & Extract| Raw
    Raw -->|Parse| Fields
    Fields -->|Calculate| Weighted
    Weighted -->|Threshold Check| Status
    Status -->|Generate| Tables
    Status -->|Generate| Chart
    Raw -->|Format| JSON
    Status -->|Display| Banner
```

### 2. Configuration Data Flow

```mermaid
flowchart TD
    subgraph Sources
        EnvFile[.env File]
        EnvExample[.env.example<br/>Template]
        Schema[JSON Schema File]
    end
    
    subgraph Runtime
        EnvVars[Environment Variables<br/>in Memory]
        SchemaData[Parsed Schema Data]
        GlobalVars[Global Configuration<br/>Constants]
    end
    
    subgraph Components
        Auth[Authentication Module]
        Client[Client Management]
        Upload[Upload Handler]
        Calc[Confidence Calculator]
    end
    
    EnvFile -.->|Loaded at Startup| EnvVars
    EnvExample -.->|User Copies & Fills| EnvFile
    Schema -->|Loaded at Startup| SchemaData
    
    EnvVars -->|Provides Credentials| Auth
    EnvVars -->|Provides URLs| Client
    SchemaData -->|Field Definitions| Calc
    SchemaData -->|Mandatory Fields| Calc
    
    GlobalVars -->|Runtime Config| Auth
    GlobalVars -->|Runtime Config| Client
    GlobalVars -->|Runtime Config| Upload
    GlobalVars -->|Runtime Config| Calc
```

---

## Integration Points

### SAP Services Integration

```mermaid
graph LR
    subgraph "Application"
        App[UAE NOC Validator]
    end
    
    subgraph "SAP BTP"
        UAA[UAA Service<br/>OAuth2 Authentication]
        DOX[DOX Service<br/>Document Extraction]
    end
    
    App -->|1. POST /oauth/token<br/>grant_type=client_credentials| UAA
    UAA -->|2. access_token| App
    App -->|3. GET /clients<br/>Authorization: Bearer token| DOX
    App -->|4. POST /clients<br/>Authorization: Bearer token| DOX
    App -->|5. POST /document/jobs<br/>file + options| DOX
    DOX -->|6. Job ID| App
    App -->|7. GET /document/jobs/{id}<br/>Poll for status| DOX
    DOX -->|8. Status updates| App
    App -->|9. GET /document/jobs/{id}<br/>extractedValues=true| DOX
    DOX -->|10. Extracted field data| App
```

---

## Component Responsibilities

### Backend Components

| Component | Responsibilities | Dependencies |
|-----------|-----------------|--------------|
| **Flask Server** | - HTTP request handling<br/>- Route management<br/>- WSGI application | - Python 3.8+<br/>- Flask 3.0.3 |
| **Dash Application** | - UI rendering<br/>- Callback management<br/>- Component updates | - Dash 2.17.0<br/>- Plotly 5.24.1 |
| **Authentication Module** | - OAuth2 token retrieval<br/>- Token management | - requests 2.31.0<br/>- SAP UAA |
| **Client Manager** | - DOX client creation<br/>- Client ID caching | - requests 2.31.0<br/>- Local file system |
| **PDF Processor** | - PDF parsing<br/>- Page splitting<br/>- Chunk generation | - PyPDF2 3.0.1 |
| **Upload Handler** | - File upload processing<br/>- DOX job submission<br/>- Status polling | - requests 2.31.0<br/>- SAP DOX |
| **Confidence Engine** | - Weighted calculations<br/>- Approximation logic<br/>- Status determination | - pandas 2.2.3 |
| **Visualization Generator** | - Chart generation<br/>- Table formatting<br/>- JSON formatting | - plotly 5.24.1<br/>- pandas 2.2.3 |

---

## Performance Considerations

### Optimization Points

1. **Token Caching**: OAuth tokens are stored in memory for the application lifetime
2. **Client ID Caching**: DOX client IDs are cached to local file system
3. **Chunk Processing**: Sequential processing to avoid quota limits
4. **Polling Optimization**: 2-second intervals with max 60 attempts (2 minutes)
5. **PDF Splitting**: Automatic chunking for large documents (>10 pages)

### Scalability Limits

| Resource | Limit | Impact |
|----------|-------|--------|
| **PDF Pages** | 10 pages per chunk | Large PDFs require multiple API calls |
| **Processing Time** | ~10-50 seconds per chunk | User must wait for sequential processing |
| **API Quota** | SAP DOX trial limits | May fail on bulk uploads |
| **Memory** | PDF size dependent | Large PDFs increase memory usage |

---

**Document Version**: 1.0  
**Last Updated**: November 2025  
**Author**: UAE NOC Validator Development Team
