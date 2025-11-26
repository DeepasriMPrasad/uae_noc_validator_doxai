"""
Schema Configuration Component for UAE NOC Validator
Professional drag-and-drop interface for configuring document schema
"""

import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import json

def create_schema_config_layout(config):
    """
    Create schema configuration screen with drag-drop interface
    
    Args:
        config (dict): Current application configuration
    
    Returns:
        html.Div: Schema configuration layout
    """
    
    # Get existing schema fields from config
    field_weights = config.get("field_weights", {})
    mandatory_fields = config.get("mandatory_fields", [])
    
    # Define all possible field types
    field_types = [
        "Text",
        "Date",
        "Number",
        "URL",
        "Email",
        "Boolean"
    ]
    
    return html.Div([
        # Header Section
        html.Div([
            html.Div([
                html.Div("🗂️", style={"fontSize": "2rem"}),
                html.Div([
                    html.H1("Schema Configuration", className="config-title"),
                    html.P(
                        "Define the document structure and field importance for AI extraction. "
                        "Drag fields to reorder, adjust weights, and mark mandatory fields.",
                        className="config-description"
                    )
                ], style={"flex": "1"})
            ], style={"display": "flex", "gap": "1rem", "alignItems": "flex-start"})
        ], className="config-header"),
        
        # Info Panel
        html.Div([
            html.Div([
                html.Span("ℹ️", style={"fontSize": "1.25rem", "marginRight": "0.5rem"}),
                html.Span("Configuration Guide", style={"fontWeight": "600"})
            ], className="info-panel-title"),
            html.Div([
                html.P("• Field weights must sum to 1.0 (100%) for accurate scoring", style={"margin": "0.25rem 0"}),
                html.P("• Mandatory fields are required for document approval", style={"margin": "0.25rem 0"}),
                html.P("• Drag the ≡ handle to reorder fields by priority", style={"margin": "0.25rem 0"}),
            ], className="info-panel-content")
        ], className="info-panel"),
        
        # Current Schema Section
        html.Div([
            html.Div([
                html.H2("Current Document Schema", className="section-title"),
                html.Button([
                    html.Span("+", style={"marginRight": "6px"}),
                    "Add Field"
                ], id="add-schema-field", className="add-button", n_clicks=0)
            ], className="section-header"),
            
            # Weight Summary
            html.Div([
                html.Span("Total Weight: ", style={"fontWeight": "600", "marginRight": "8px"}),
                html.Span(
                    f"{sum(field_weights.values()):.3f}",
                    id="weight-total",
                    style={
                        "padding": "4px 12px",
                        "background": "#E5F5ED" if abs(sum(field_weights.values()) - 1.0) < 0.001 else "#FFF3E8",
                        "borderRadius": "4px",
                        "fontWeight": "600",
                        "color": "#107E3E" if abs(sum(field_weights.values()) - 1.0) < 0.001 else "#E9730C"
                    }
                ),
                html.Span(
                    " ✓ Valid" if abs(sum(field_weights.values()) - 1.0) < 0.001 else " ⚠ Must equal 1.0",
                    style={
                        "marginLeft": "8px",
                        "fontSize": "0.875rem",
                        "color": "#107E3E" if abs(sum(field_weights.values()) - 1.0) < 0.001 else "#E9730C"
                    }
                )
            ], style={"marginBottom": "1.5rem", "display": "flex", "alignItems": "center"}),
            
            # Schema Fields List
            html.Div(
                [
                    create_schema_field_item(
                        field_name,
                        weight,
                        field_name in mandatory_fields,
                        idx
                    )
                    for idx, (field_name, weight) in enumerate(field_weights.items())
                ],
                id="schema-fields-list",
                className="schema-list"
            ),
            
        ], className="config-section"),
        
        # Action Buttons
        html.Div([
            html.Button("Cancel", id="schema-cancel", className="sap-button secondary", 
                       style={"marginRight": "1rem"}),
            html.Button("Save Schema", id="schema-save", className="sap-button"),
        ], style={"display": "flex", "justifyContent": "flex-end", "marginTop": "2rem"}),
        
        # Hidden stores for data
        dcc.Store(id="schema-data-store", data=field_weights),
        dcc.Store(id="mandatory-fields-store", data=mandatory_fields),
        
    ], className="config-screen")


def create_schema_field_item(field_name, weight, is_mandatory, index):
    """Create a single schema field row"""
    
    # Friendly labels for common fields
    friendly_labels = {
        "applicationNumber": "Application Number",
        "issuingAuthority": "Issuing Authority",
        "ownerName": "Owner Name",
        "issueDate": "Issue Date",
        "approvalUrl": "Approval URL",
        "allocationDate": "Allocation Date",
        "documentStatus": "Document Status"
    }
    
    display_name = friendly_labels.get(field_name, field_name)
    
    return html.Div([
        # Drag Handle
        html.Div("≡", className="drag-handle", draggable=True),
        
        # Field Content
        html.Div([
            # Field Name Input
            html.Div([
                html.Label("Field Name", style={"fontSize": "0.75rem", "color": "#6A6D70", "marginBottom": "4px"}),
                html.Input(
                    type="text",
                    value=display_name,
                    className="field-input",
                    id={"type": "field-name", "index": index}
                )
            ]),
            
            # Field Type Select
            html.Div([
                html.Label("Type", style={"fontSize": "0.75rem", "color": "#6A6D70", "marginBottom": "4px"}),
                html.Select(
                    ["Text", "Date", "Number", "URL", "Email"],
                    value="Text",
                    className="field-select",
                    id={"type": "field-type", "index": index}
                )
            ]),
            
            # Weight Input
            html.Div([
                html.Label("Weight", style={"fontSize": "0.75rem", "color": "#6A6D70", "marginBottom": "4px"}),
                html.Input(
                    type="number",
                    value=weight,
                    min=0,
                    max=1,
                    step=0.01,
                    className="field-weight",
                    id={"type": "field-weight", "index": index}
                )
            ]),
            
            # Mandatory Badge
            html.Div([
                html.Label("Status", style={"fontSize": "0.75rem", "color": "#6A6D70", "marginBottom": "4px"}),
                html.Div([
                    html.Span(
                        "Mandatory" if is_mandatory else "Optional",
                        className=f"field-badge {'mandatory' if is_mandatory else 'optional'}"
                    )
                ])
            ]),
            
        ], className="schema-item-content"),
        
        # Remove Button
        html.Button(
            "Remove",
            id={"type": "remove-field", "index": index},
            className="remove-button",
            n_clicks=0
        )
        
    ], className="schema-item", **{"data-index": index})


# Sample callback structure (to be integrated into main app)
"""
@dash_app.callback(
    Output("schema-fields-list", "children"),
    [Input("add-schema-field", "n_clicks"),
     Input({"type": "remove-field", "index": ALL}, "n_clicks")],
    [State("schema-fields-list", "children"),
     State("schema-data-store", "data")],
    prevent_initial_call=True
)
def update_schema_fields(add_clicks, remove_clicks, current_fields, schema_data):
    ctx = dash.callback_context
    
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger_id = ctx.triggered[0]["prop_id"]
    
    if "add-schema-field" in trigger_id:
        # Add new field
        new_index = len(current_fields)
        new_field = create_schema_field_item(
            f"newField{new_index}",
            0.0,
            False,
            new_index
        )
        current_fields.append(new_field)
    
    elif "remove-field" in trigger_id:
        # Remove field
        trigger = json.loads(trigger_id.split(".")[0])
        index_to_remove = trigger["index"]
        current_fields = [f for i, f in enumerate(current_fields) if i != index_to_remove]
    
    return current_fields


@dash_app.callback(
    [Output("weight-total", "children"),
     Output("weight-total", "style")],
    [Input({"type": "field-weight", "index": ALL}, "value")],
    prevent_initial_call=True
)
def update_weight_total(weights):
    total = sum(w for w in weights if w is not None)
    is_valid = abs(total - 1.0) < 0.001
    
    style = {
        "padding": "4px 12px",
        "background": "#E5F5ED" if is_valid else "#FFF3E8",
        "borderRadius": "4px",
        "fontWeight": "600",
        "color": "#107E3E" if is_valid else "#E9730C"
    }
    
    return f"{total:.3f}", style
"""
