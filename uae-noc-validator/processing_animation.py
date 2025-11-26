"""
Professional Processing Animation Component for UAE NOC Validator
SAP Fiori-styled multi-stage processing visualization
"""

import dash
from dash import html, dcc

def create_processing_animation(current_stage="upload", progress=0):
    """
    Create professional processing overlay with stage indicators
    
    Args:
        current_stage (str): Current processing stage
        progress (int): Progress percentage (0-100)
    
    Returns:
        html.Div: Processing animation overlay
    """
    
    # Define processing stages
    stages = [
        {
            "id": "upload",
            "icon": "📤",
            "label": "Document Upload",
            "description": "Securely uploading to SAP Document AI",
            "svg_icon": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M9 16h6v-6h4l-7-7-7 7h4v6zm-4 2h14v2H5v-2z" fill="currentColor"/>
            </svg>"""
        },
        {
            "id": "analysis",
            "icon": "🔍",
            "label": "AI Analysis",
            "description": "Extracting fields using machine learning",
            "svg_icon": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/>
            </svg>"""
        },
        {
            "id": "validation",
            "icon": "✓",
            "label": "Rule Validation",
            "description": "Checking business rule compliance",
            "svg_icon": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z" fill="currentColor"/>
            </svg>"""
        },
        {
            "id": "scoring",
            "icon": "📊",
            "label": "Confidence Scoring",
            "description": "Calculating weighted confidence",
            "svg_icon": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z" fill="currentColor"/>
            </svg>"""
        },
        {
            "id": "complete",
            "icon": "✓",
            "label": "Complete",
            "description": "Results ready for review",
            "svg_icon": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/>
            </svg>"""
        }
    ]
    
    # Determine stage states
    current_index = next((i for i, s in enumerate(stages) if s["id"] == current_stage), 0)
    
    stage_items = []
    for idx, stage in enumerate(stages):
        if idx < current_index:
            state = "completed"
            icon_class = "completed"
        elif idx == current_index:
            state = "active"
            icon_class = "active"
        else:
            state = "pending"
            icon_class = "pending"
        
        stage_items.append(
            html.Div([
                html.Div([
                    html.Div(stage["icon"], style={"fontSize": "1.25rem"})
                ], className=f"step-icon {icon_class}"),
                
                html.Div([
                    html.Div(stage["label"], className="step-label"),
                    html.Div(stage["description"], className="step-detail"),
                ], className="step-content"),
                
            ], className=f"step-item {state}")
        )
    
    return html.Div([
        html.Div([
            # Processing Stage
            html.Div([
                html.Div(
                    stages[current_index]["label"],
                    className="stage-title"
                ),
                html.Div(
                    stages[current_index]["description"],
                    className="stage-description"
                ),
            ], className="processing-stage"),
            
            # Progress Bar
            html.Div([
                html.Div(
                    style={"width": f"{progress}%"},
                    className="progress-bar"
                )
            ], className="progress-bar-container"),
            
            # Stage Steps
            html.Div(stage_items, className="processing-steps"),
            
        ], className="processing-container")
    ], className="processing-overlay", id="processing-overlay")


def create_processing_animation_simple():
    """
    Create simplified processing animation for initial display
    """
    return html.Div([
        html.Div([
            html.Div("⚙️", style={"fontSize": "3rem", "marginBottom": "1rem"}),
            html.Div("Processing Document", style={
                "fontSize": "1.25rem",
                "fontWeight": "600",
                "marginBottom": "0.5rem"
            }),
            html.Div("Please wait while we analyze your document", style={
                "fontSize": "0.875rem",
                "color": "#6A6D70",
                "marginBottom": "2rem"
            }),
            html.Div([
                html.Div(className="progress-bar", style={"width": "30%"})
            ], className="progress-bar-container"),
        ], className="processing-container")
    ], className="processing-overlay", id="processing-overlay", style={"display": "none"})


# JavaScript for controlling the animation
processing_animation_js = """
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    clientside: {
        updateProcessingStage: function(current_stage, progress) {
            // Update processing overlay based on current stage
            const overlay = document.getElementById('processing-overlay');
            if (!overlay) return window.dash_clientside.no_update;
            
            if (current_stage === null || current_stage === 'complete') {
                overlay.style.display = 'none';
                return window.dash_clientside.no_update;
            }
            
            overlay.style.display = 'flex';
            return window.dash_clientside.no_update;
        },
        
        hideOtherComponents: function(is_processing) {
            // Hide gauge, tables, and charts while processing
            const componentsToHide = [
                'confidence-gauge',
                'table-mandatory',
                'table-explain',
                'graph-explain',
                'verdict-banner',
                'pdf-preview-section'
            ];
            
            componentsToHide.forEach(id => {
                const element = document.getElementById(id);
                if (element) {
                    if (is_processing) {
                        element.style.display = 'none';
                    } else {
                        element.style.display = '';
                    }
                }
            });
            
            return window.dash_clientside.no_update;
        }
    }
});
"""


# Sample callback structure for controlling the animation
"""
@dash_app.callback(
    [Output("processing-overlay", "children"),
     Output("processing-overlay", "style")],
    [Input("processing-stage-store", "data"),
     Input("processing-progress-store", "data")],
    prevent_initial_call=True
)
def update_processing_animation(stage_data, progress_data):
    if stage_data is None:
        return no_update, {"display": "none"}
    
    current_stage = stage_data.get("stage", "upload")
    progress = stage_data.get("progress", 0)
    
    if current_stage == "complete":
        return no_update, {"display": "none"}
    
    animation = create_processing_animation(current_stage, progress)
    return animation.children, {"display": "flex"}


@dash_app.callback(
    Output("main-results-container", "style"),
    Input("processing-stage-store", "data"),
    prevent_initial_call=True
)
def toggle_results_visibility(stage_data):
    if stage_data is None:
        return {"display": "block"}
    
    current_stage = stage_data.get("stage", "upload")
    
    if current_stage == "complete":
        return {"display": "block"}
    else:
        return {"display": "none"}
"""
