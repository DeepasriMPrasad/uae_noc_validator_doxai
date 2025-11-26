"""
Business Rules Configuration Component for UAE NOC Validator
Professional interface for configuring validation rules
"""

import dash
from dash import html, dcc, Input, Output, State, callback
import json

def create_rules_config_layout(config):
    """
    Create business rules configuration screen
    
    Args:
        config (dict): Current application configuration
    
    Returns:
        html.Div: Rules configuration layout
    """
    
    # Get existing validation rules from config
    validation_rules = config.get("validation_rules", {})
    
    return html.Div([
        # Header Section
        html.Div([
            html.Div([
                html.Div("📏", style={"fontSize": "2rem"}),
                html.Div([
                    html.H1("Business Rules Configuration", className="config-title"),
                    html.P(
                        "Define validation rules that go beyond AI confidence scores. "
                        "These rules ensure documents meet your business requirements.",
                        className="config-description"
                    )
                ], style={"flex": "1"})
            ], style={"display": "flex", "gap": "1rem", "alignItems": "flex-start"})
        ], className="config-header"),
        
        # Info Panel
        html.Div([
            html.Div([
                html.Span("ℹ️", style={"fontSize": "1.25rem", "marginRight": "0.5rem"}),
                html.Span("Available Rule Types", style={"fontWeight": "600"})
            ], className="info-panel-title"),
            html.Div([
                html.P("• Date Age: Ensure dates are within a specified time limit", style={"margin": "0.25rem 0"}),
                html.P("• Whitelist: Check if values match approved list of options", style={"margin": "0.25rem 0"}),
                html.P("• Regex: Validate format using regular expressions (coming soon)", style={"margin": "0.25rem 0"}),
                html.P("• Range: Verify numeric values fall within expected range (coming soon)", style={"margin": "0.25rem 0"}),
            ], className="info-panel-content")
        ], className="info-panel"),
        
        # Current Rules Section
        html.Div([
            html.Div([
                html.H2("Active Validation Rules", className="section-title"),
                html.Button([
                    html.Span("+", style={"marginRight": "6px"}),
                    "Add Rule"
                ], id="add-rule", className="add-button", n_clicks=0)
            ], className="section-header"),
            
            # Rules List
            html.Div(
                [
                    create_rule_card(field_name, rule_config, idx)
                    for idx, (field_name, rule_config) in enumerate(validation_rules.items())
                ],
                id="rules-list",
                className="rules-list"
            ),
            
        ], className="config-section"),
        
        # Rule Templates Section
        html.Div([
            html.H2("Rule Templates", className="section-title", style={"marginBottom": "1rem"}),
            
            html.Div([
                # Date Age Template
                html.Div([
                    html.Div([
                        html.Div("📅", style={"fontSize": "1.5rem"}),
                        html.Div([
                            html.H3("Date Age Rule", style={"fontSize": "1rem", "margin": "0 0 0.25rem 0"}),
                            html.P("Validate that dates are within a specified age limit", 
                                  style={"fontSize": "0.875rem", "color": "#6A6D70", "margin": "0"})
                        ])
                    ], style={"display": "flex", "gap": "1rem", "marginBottom": "1rem"}),
                    html.Button("Use Template", className="sap-button secondary", 
                               style={"width": "100%"})
                ], style={"flex": "1", "padding": "1.5rem", "background": "#F5F5F5", 
                         "borderRadius": "6px", "border": "1px solid #D9D9D9"}),
                
                # Whitelist Template
                html.Div([
                    html.Div([
                        html.Div("📋", style={"fontSize": "1.5rem"}),
                        html.Div([
                            html.H3("Whitelist Rule", style={"fontSize": "1rem", "margin": "0 0 0.25rem 0"}),
                            html.P("Check if extracted value matches approved options", 
                                  style={"fontSize": "0.875rem", "color": "#6A6D70", "margin": "0"})
                        ])
                    ], style={"display": "flex", "gap": "1rem", "marginBottom": "1rem"}),
                    html.Button("Use Template", className="sap-button secondary", 
                               style={"width": "100%"})
                ], style={"flex": "1", "padding": "1.5rem", "background": "#F5F5F5", 
                         "borderRadius": "6px", "border": "1px solid #D9D9D9"}),
                
                # Regex Template (Coming Soon)
                html.Div([
                    html.Div([
                        html.Div("🔤", style={"fontSize": "1.5rem"}),
                        html.Div([
                            html.H3("Regex Pattern", style={"fontSize": "1rem", "margin": "0 0 0.25rem 0"}),
                            html.P("Validate format using regular expressions (Coming Soon)", 
                                  style={"fontSize": "0.875rem", "color": "#6A6D70", "margin": "0"})
                        ])
                    ], style={"display": "flex", "gap": "1rem", "marginBottom": "1rem"}),
                    html.Button("Coming Soon", className="sap-button secondary", 
                               style={"width": "100%"}, disabled=True)
                ], style={"flex": "1", "padding": "1.5rem", "background": "#F5F5F5", 
                         "borderRadius": "6px", "border": "1px solid #D9D9D9", "opacity": "0.6"}),
                
            ], style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "1rem"}),
            
        ], className="config-section"),
        
        # Action Buttons
        html.Div([
            html.Button("Cancel", id="rules-cancel", className="sap-button secondary", 
                       style={"marginRight": "1rem"}),
            html.Button("Save Rules", id="rules-save", className="sap-button"),
        ], style={"display": "flex", "justifyContent": "flex-end", "marginTop": "2rem"}),
        
        # Hidden store for data
        dcc.Store(id="rules-data-store", data=validation_rules),
        
    ], className="config-screen")


def create_rule_card(field_name, rule_config, index):
    """Create a single rule card"""
    
    rule_type = rule_config.get("type", "unknown")
    
    # Friendly labels
    friendly_labels = {
        "applicationNumber": "Application Number",
        "issuingAuthority": "Issuing Authority",
        "ownerName": "Owner Name",
        "issueDate": "Issue Date",
        "approvalUrl": "Approval URL",
        "allocationDate": "Allocation Date"
    }
    
    display_name = friendly_labels.get(field_name, field_name)
    
    # Type-specific content
    if rule_type == "date_age":
        rule_body = create_date_age_rule_body(rule_config)
    elif rule_type == "whitelist":
        rule_body = create_whitelist_rule_body(rule_config)
    else:
        rule_body = html.Div("Unknown rule type", style={"color": "#BB0000"})
    
    return html.Div([
        # Rule Header
        html.Div([
            html.Div([
                html.Span(display_name, style={"fontWeight": "600", "fontSize": "0.875rem"}),
                html.Span(
                    rule_type.upper().replace("_", " "),
                    className=f"rule-type-badge {rule_type.replace('_', '')}"
                )
            ], className="rule-title"),
            
            html.Button(
                "Remove",
                id={"type": "remove-rule", "index": index},
                className="remove-button",
                style={"minWidth": "60px"},
                n_clicks=0
            )
        ], className="rule-header"),
        
        # Rule Body
        rule_body,
        
    ], className="rule-card")


def create_date_age_rule_body(rule_config):
    """Create body for date age rule"""
    
    max_age = rule_config.get("max_age_months", 6)
    error_msg = rule_config.get("error_message", "")
    
    return html.Div([
        # Left Column
        html.Div([
            html.Div([
                html.Label("Maximum Age (Months)", className="rule-label"),
                html.Input(
                    type="number",
                    value=max_age,
                    className="rule-value",
                    min=1,
                    max=120
                )
            ], className="rule-field"),
            
            html.Div([
                html.Label("Calculated Days", className="rule-label"),
                html.Div(
                    f"≈ {int(max_age * 30.44)} days",
                    style={
                        "padding": "8px 12px",
                        "background": "#F5F5F5",
                        "borderRadius": "4px",
                        "fontSize": "0.875rem",
                        "color": "#6A6D70"
                    }
                )
            ], className="rule-field"),
        ]),
        
        # Right Column
        html.Div([
            html.Div([
                html.Label("Error Message", className="rule-label"),
                html.Textarea(
                    value=error_msg,
                    className="rule-value",
                    style={"minHeight": "80px", "resize": "vertical"}
                )
            ], className="rule-field"),
        ]),
        
    ], className="rule-body")


def create_whitelist_rule_body(rule_config):
    """Create body for whitelist rule"""
    
    allowed_values = rule_config.get("allowed_values", [])
    case_sensitive = rule_config.get("case_sensitive", False)
    fuzzy_match = rule_config.get("fuzzy_match", False)
    error_msg = rule_config.get("error_message", "")
    
    return html.Div([
        # Left Column
        html.Div([
            html.Div([
                html.Label("Allowed Values", className="rule-label"),
                html.Div([
                    html.Span(
                        value,
                        className="value-chip",
                        children=[
                            html.Span(value),
                            html.Span("×", className="value-chip-remove")
                        ]
                    )
                    for value in allowed_values[:5]  # Show first 5
                ] + ([
                    html.Span(
                        f"+{len(allowed_values) - 5} more",
                        style={
                            "fontSize": "0.75rem",
                            "color": "#6A6D70",
                            "padding": "4px 10px"
                        }
                    )
                ] if len(allowed_values) > 5 else []),
                className="values-list"
                )
            ], className="rule-field"),
            
            html.Div([
                html.Label("Options", className="rule-label"),
                html.Div([
                    html.Label([
                        html.Input(type="checkbox", checked=case_sensitive, 
                                 style={"marginRight": "6px"}),
                        "Case Sensitive"
                    ], style={"fontSize": "0.875rem", "display": "block", "marginBottom": "8px"}),
                    html.Label([
                        html.Input(type="checkbox", checked=fuzzy_match, 
                                 style={"marginRight": "6px"}),
                        "Fuzzy Match"
                    ], style={"fontSize": "0.875rem", "display": "block"}),
                ], style={"padding": "8px 12px", "background": "#F5F5F5", "borderRadius": "4px"})
            ], className="rule-field"),
        ]),
        
        # Right Column
        html.Div([
            html.Div([
                html.Label("Error Message", className="rule-label"),
                html.Textarea(
                    value=error_msg,
                    className="rule-value",
                    style={"minHeight": "150px", "resize": "vertical"}
                )
            ], className="rule-field"),
        ]),
        
    ], className="rule-body")


# Sample callback structure (to be integrated into main app)
"""
@dash_app.callback(
    Output("rules-list", "children"),
    [Input("add-rule", "n_clicks"),
     Input({"type": "remove-rule", "index": ALL}, "n_clicks")],
    [State("rules-list", "children"),
     State("rules-data-store", "data")],
    prevent_initial_call=True
)
def update_rules_list(add_clicks, remove_clicks, current_rules, rules_data):
    ctx = dash.callback_context
    
    if not ctx.triggered:
        raise PreventUpdate
    
    trigger_id = ctx.triggered[0]["prop_id"]
    
    if "add-rule" in trigger_id:
        # Add new rule (open dialog to select field and type)
        pass
    
    elif "remove-rule" in trigger_id:
        # Remove rule
        trigger = json.loads(trigger_id.split(".")[0])
        index_to_remove = trigger["index"]
        current_rules = [r for i, r in enumerate(current_rules) if i != index_to_remove]
    
    return current_rules
"""
