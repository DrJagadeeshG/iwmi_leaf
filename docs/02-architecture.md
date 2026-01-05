# LEAF DSS - Core Architecture

## Overview

LEAF DSS is a web-based Decision Support System for evaluating agricultural intervention feasibility across geographic regions. The application follows a three-tier architecture with clear separation between data, logic, and presentation layers.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  Leaflet.js │  │  Chart.js   │  │   Custom JavaScript     │ │
│  │    (Map)    │  │  (Charts)   │  │   (app.js - Logic)      │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│                              │                                   │
│                    HTML/CSS (index.html, style.css)             │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP/REST API
┌──────────────────────────────┴──────────────────────────────────┐
│                      SERVER (Flask + Gunicorn)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   app.py    │  │ feasibility │  │     data_utils.py       │ │
│  │  (Routes)   │  │    .py      │  │   (Data Loading)        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│                              │                                   │
│                        config.py                                 │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────────┐
│                         DATA LAYER                               │
│  ┌─────────────────────────┐  ┌───────────────────────────────┐ │
│  │   4DSS_VAR_2.0.shp      │  │      DSS_input2.csv           │ │
│  │   (Shapefile - Blocks)  │  │   (Variable Metadata)         │ │
│  └─────────────────────────┘  └───────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
leaf_flask/
├── app.py              # Flask application & API routes
├── config.py           # Configuration (colors, interventions, map settings)
├── data_utils.py       # Data loading and processing utilities
├── feasibility.py      # Feasibility calculation logic
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container configuration
├── render.yaml         # Render deployment config
├── data/
│   ├── 4DSS_VAR_2.0.*  # Shapefile (shp, shx, dbf, prj, cpg)
│   └── DSS_input2.csv  # Variable metadata
├── static/
│   ├── css/
│   │   └── style.css   # Application styles (IWMI branding)
│   ├── js/
│   │   └── app.js      # Frontend JavaScript logic
│   └── images/
│       ├── iwmi_logo.png
│       └── cgiar_logo.png
├── templates/
│   └── index.html      # Main HTML template
└── docs/
    └── *.md            # Documentation
```

## Component Details

### Backend (Python/Flask)

#### app.py - API Routes
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve main dashboard |
| `/api/blocks` | GET | Get all blocks as GeoJSON |
| `/api/interventions` | GET | List available interventions |
| `/api/intervention/<name>/config` | GET | Get intervention configuration |
| `/api/calculate-feasibility` | POST | Calculate feasibility scores |
| `/api/export/csv` | POST | Export data as CSV |
| `/health` | GET | Health check endpoint |

#### data_utils.py - Data Loading
- `load_shapefile()` - Load and cache shapefile with LRU caching
- `load_metadata()` - Load variable metadata CSV
- `get_intervention_config()` - Extract intervention configurations
- `get_blocks_geojson()` - Convert GeoDataFrame to GeoJSON

#### feasibility.py - Calculation Engine
- `calculate_feasibility_score()` - Score individual blocks
- `add_feasibility_to_gdf()` - Add scores to GeoDataFrame
- `classify_feasibility()` - Classify into categories (Very High, High, etc.)
- `get_feasibility_distribution()` - Calculate distribution statistics

#### config.py - Configuration
- IWMI brand colors
- Feasibility color scheme
- Intervention definitions
- Map configuration (center, zoom, bounds)

### Frontend (JavaScript)

#### app.js - Main Application Logic
```javascript
// State Management
const state = {
    map: null,
    geojsonLayer: null,
    chart: null,
    currentIntervention: null,
    currentFilters: [],
    logic: 'AND'
};

// Key Functions
- initMap()              // Initialize Leaflet map
- loadIntervention()     // Load intervention config
- calculateFeasibility() // Call API and update map
- updateChart()          // Update distribution chart
- updateActiveFilters()  // Update filter display
- exportCSV()            // Export data
```

### Styling (CSS)

#### style.css - IWMI Branding
```css
/* Brand Colors */
--iwmi-dark-blue: #28537D
--iwmi-teal: #0297A6
--iwmi-green: #22AD7A
--iwmi-sky-blue: #46BBD4

/* Feasibility Colors */
--feas-very-high: #1b5e20
--feas-high: #81c784
--feas-moderate: #ffd700
--feas-low: #ff8c00
--feas-very-low: #ff0000
```

## Data Flow

### Feasibility Calculation Flow

```
1. User selects intervention
        │
        ▼
2. Frontend calls /api/intervention/<name>/config
        │
        ▼
3. Backend returns variable configurations
        │
        ▼
4. User adjusts filters (optional)
        │
        ▼
5. Frontend calls /api/calculate-feasibility (POST)
   {
     "intervention": "Organic Farming",
     "filters": [...],
     "logic": "AND"
   }
        │
        ▼
6. Backend:
   - Loads shapefile (cached)
   - Applies filters to each block
   - Calculates feasibility scores
   - Classifies into categories
   - Returns GeoJSON with scores
        │
        ▼
7. Frontend:
   - Updates map layer colors
   - Updates distribution chart
   - Updates legend percentages
```

## Caching Strategy

### Server-side (Python)
- `@lru_cache` on data loading functions
- Shapefile loaded once, reused for all requests

### Client-side (Browser)
- Static assets cached by browser
- API responses can be cached with appropriate headers

## Security Considerations

- CORS enabled for API endpoints
- Input validation on all API parameters
- No direct database access (file-based data)
- Environment variables for sensitive configuration

---

## Planned Feature: Block Detail View

### Overview

Similar to the SolaReady dashboard's district detail view, LEAF DSS will implement a **single-page application (SPA) with view switching** to display detailed block-level information when a user clicks on a block.

### View Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        index.html                                │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  #overviewView (Default - visible)                          ││
│  │  ┌─────────────┬─────────────┬─────────────────────────────┐││
│  │  │    Map      │Distribution │    Active Filters           │││
│  │  │  (Leaflet)  │  (Chart.js) │       (Table)               │││
│  │  └─────────────┴─────────────┴─────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  #blockDetailView (Hidden by default)                       ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │  Back to Overview | Block Name | Feasibility Status     │││
│  │  ├─────────────────────────────────────────────────────────┤││
│  │  │  ┌──────────┬──────────┬──────────┬──────────┬────────┐│││
│  │  │  │ Location │Land/Agri │  Water   │Livestock │ People ││││
│  │  │  │ Mini-map │ Metrics  │ Metrics  │ Metrics  │Metrics ││││
│  │  │  └──────────┴──────────┴──────────┴──────────┴────────┘│││
│  │  └─────────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### View Switching Logic

```javascript
// State
let currentBlock = null;

// Show Overview (default)
function showOverviewView() {
    document.getElementById('overviewView').style.display = 'block';
    document.getElementById('blockDetailView').style.display = 'none';
    currentBlock = null;
}

// Show Block Detail
function showBlockDetailView(blockId) {
    document.getElementById('overviewView').style.display = 'none';
    document.getElementById('blockDetailView').style.display = 'block';
    currentBlock = blockId;
    loadBlockData(blockId);
}

// Triggered by:
// 1. Clicking on a block polygon in the map
// 2. Back button returns to overview
```

### Block Detail View Components

| Section | Description |
|---------|-------------|
| **Header** | Block name, district, state + Back to Overview link |
| **Feasibility Status** | Color-coded badges showing feasibility for selected intervention |
| **Location Card** | Mini-map showing the selected block boundary |
| **Land & Agriculture** | Cropping intensity, paddy area, horticulture, crop diversification |
| **Water** | Irrigation coverage, groundwater development, micro-irrigation |
| **Infrastructure** | Markets, banks, custom hiring, soil testing centres |
| **Livestock** | Cattle/buffalo density, veterinary services, milk collection |
| **People** | SHGs, FPOs, literacy rate, farmer categories |

### New API Endpoint

```
GET /api/block-data/<block_id>
```

**Response:**
```json
{
  "block_id": "BLOCK_001",
  "block_name": "Example Block",
  "district": "Example District",
  "state": "Odisha",
  "feasibility": {
    "score": 0.75,
    "category": "High",
    "color": "#81c784"
  },
  "metrics": {
    "land_agri": {
      "cropping_intensity": { "value": 142.5, "unit": "%" },
      "paddy_area": { "value": 35.2, "unit": "%" },
      "horticulture_area": { "value": 12.8, "unit": "%" }
    },
    "water": {
      "irrigation_coverage": { "value": 68.4, "unit": "%" },
      "gw_development": { "value": 45.2, "unit": "%" }
    },
    "infrastructure": { ... },
    "livestock": { ... },
    "people": { ... }
  }
}
```

### Implementation Steps

1. **HTML Structure**
   - Add `#blockDetailView` div (hidden by default)
   - Create grid layout for metric cards
   - Add mini-map container

2. **CSS Styling**
   - Block detail grid layout
   - Metric card styling (matching Solar dashboard)
   - Status badges
   - Back button styling

3. **JavaScript**
   - `showOverviewView()` / `showBlockDetailView()` functions
   - `loadBlockData(blockId)` API call
   - `renderBlockDetail(data)` to populate UI
   - Mini-map initialization for selected block
   - Update map click handler to trigger view switch

4. **Backend**
   - Add `/api/block-data/<block_id>` endpoint
   - Return all variable values for the block
   - Include feasibility calculation for current intervention

### Reference: SolaReady Implementation

The SolaReady dashboard uses this exact pattern:
- `#nationalView` ↔ `#districtView` toggle
- Click on map district → `showDistrictView()`
- Back link → `navigateToOverview()`
- API: `/api/district-data/<state>/<district>`

LEAF DSS will follow the same pattern for consistency across IWMI tools.
