# Business Rule Validation Guide

## Overview

The UAE NOC Validator supports configurable business rules to validate extracted document fields beyond AI confidence scores. This guide explains how to add and configure validation rules.

---

## Table of Contents

1. [Built-in Rule Types](#built-in-rule-types)
2. [Adding Rules to config.json](#adding-rules-to-configjson)
3. [Adding New Rule Types](#adding-new-rule-types)
4. [Examples](#examples)
5. [Troubleshooting](#troubleshooting)

---

## Built-in Rule Types

### 1. Date Age Validation (`date_age`)

Checks if a date field is within a specified age limit.

**Configuration:**
```json
{
  "validation_rules": {
    "issueDate": {
      "type": "date_age",
      "max_age_months": 6,
      "error_message": "NOC must be issued within the last 6 months"
    }
  }
}
```

**Parameters:**
- `type`: Must be `"date_age"`
- `max_age_months`: Maximum allowed age in months (required)
- `error_message`: Custom error message to display (optional)

**Behavior:**
- Parses dates in multiple formats (DD/MM/YYYY, YYYY-MM-DD, etc.)
- Calculates age from current date
- Fails if date is older than `max_age_months`

---

### 2. Whitelist Validation (`whitelist`)

Checks if a field value is in an approved list of values.

**Configuration:**
```json
{
  "validation_rules": {
    "issuingAuthority": {
      "type": "whitelist",
      "allowed_values": [
        "Dubai Municipality",
        "Abu Dhabi DED",
        "Sharjah Municipality"
      ],
      "case_sensitive": false,
      "fuzzy_match": true,
      "error_message": "Authority must be from approved list"
    }
  }
}
```

**Parameters:**
- `type`: Must be `"whitelist"`
- `allowed_values`: Array of approved values (required)
- `case_sensitive`: Whether matching is case-sensitive (default: false)
- `fuzzy_match`: Allow partial matches (default: false)
- `error_message`: Custom error message (optional)

**Behavior:**
- Case-insensitive matching by default
- Fuzzy matching checks if extracted value contains or is contained in allowed value
- Trims whitespace before comparison

---

## Adding Rules to config.json

### Step 1: Open config.json

```json
{
  "version": "2.0.0",
  "port": 7070,
  "validation_rules": {
    // Add rules here
  }
}
```

### Step 2: Add Rule for Each Field

Format:
```json
"validation_rules": {
  "fieldName": {
    "type": "rule_type",
    "parameter1": "value1",
    "parameter2": "value2"
  }
}
```

### Step 3: Restart Application

Changes take effect after restarting the application.

---

## Adding New Rule Types

### Implementation Steps

#### 1. Add Rule Logic to `validate_business_rules` Function

Location: `app.py` → `validate_business_rules` function

```python
def validate_business_rules(fields, job=None):
    # ... existing code ...
    
    for field_name, rule in validation_rules.items():
        field_data = fields.get(field_name, {})
        value = field_data.get("value")
        
        # ... existing validations ...
        
        # ADD YOUR NEW RULE TYPE HERE
        elif rule.get("type") == "your_rule_type":
            # Your validation logic
            try:
                # Extract rule parameters
                param1 = rule.get("param1")
                param2 = rule.get("param2")
                
                # Perform validation
                is_valid = your_validation_logic(value, param1, param2)
                
                if not is_valid:
                    # Validation failed
                    violations.append(
                        f"❌ {FRIENDLY_LABELS.get(field_name, field_name)}: "
                        f"Your error message here. "
                        f"{rule.get('error_message', '')}"
                    )
                    validation_details[field_name] = {
                        "status": "failed",
                        "value": value,
                        "error": rule.get('error_message', '')
                    }
                    if job:
                        job.add_log(f"❌ Validation failed: {field_name}")
                else:
                    # Validation passed
                    validation_details[field_name] = {
                        "status": "passed",
                        "value": value
                    }
                    if job:
                        job.add_log(f"✅ Validation passed: {field_name}")
                        
            except Exception as e:
                # Handle errors
                warnings.append(
                    f"⚠️ {FRIENDLY_LABELS.get(field_name, field_name)}: "
                    f"Validation error: {str(e)}"
                )
                validation_details[field_name] = {
                    "status": "error",
                    "value": value,
                    "error": str(e)
                }
```

#### 2. Test Your Rule

Create test case in config.json:
```json
{
  "validation_rules": {
    "testField": {
      "type": "your_rule_type",
      "param1": "value1"
    }
  }
}
```

---

## Examples

### Example 1: Multiple Date Validations

Validate both issue and expiry dates:

```json
{
  "validation_rules": {
    "issueDate": {
      "type": "date_age",
      "max_age_months": 6,
      "error_message": "NOC issue date must be within 6 months"
    },
    "expiryDate": {
      "type": "date_age",
      "max_age_months": -12,
      "error_message": "NOC must not be expired (valid for 1 year)"
    }
  }
}
```

**Note:** Use negative `max_age_months` for future dates.

---

### Example 2: Multiple Whitelist Validations

Validate multiple authority fields:

```json
{
  "validation_rules": {
    "issuingAuthority": {
      "type": "whitelist",
      "allowed_values": [
        "Dubai Municipality",
        "Abu Dhabi DED",
        "Sharjah Municipality",
        "Ajman Municipality"
      ],
      "fuzzy_match": true,
      "error_message": "Authority not recognized"
    },
    "documentStatus": {
      "type": "whitelist",
      "allowed_values": ["Approved", "Active", "Valid"],
      "case_sensitive": false,
      "error_message": "Invalid document status"
    }
  }
}
```

---

### Example 3: Regex Pattern Validation (Custom Implementation)

**Step 1: Add regex validation to code**

```python
# In validate_business_rules function
elif rule.get("type") == "regex":
    import re
    
    pattern = rule.get("pattern")
    if not pattern:
        warnings.append(f"⚠️ No regex pattern provided for {field_name}")
        continue
    
    try:
        regex = re.compile(pattern)
        is_valid = bool(regex.match(value))
        
        if not is_valid:
            violations.append(
                f"❌ {FRIENDLY_LABELS.get(field_name, field_name)}: "
                f"Value '{value}' does not match required format. "
                f"{rule.get('error_message', '')}"
            )
            validation_details[field_name] = {
                "status": "failed",
                "value": value,
                "pattern": pattern,
                "error": rule.get('error_message', '')
            }
        else:
            validation_details[field_name] = {
                "status": "passed",
                "value": value,
                "pattern": pattern
            }
    except re.error as e:
        warnings.append(f"⚠️ Invalid regex pattern for {field_name}: {e}")
```

**Step 2: Use in config.json**

```json
{
  "validation_rules": {
    "applicationNumber": {
      "type": "regex",
      "pattern": "^NOC-\\d{4}-\\d{6}$",
      "error_message": "Application number must be in format NOC-YYYY-NNNNNN"
    },
    "phoneNumber": {
      "type": "regex",
      "pattern": "^\\+971\\d{9}$",
      "error_message": "Phone number must be in UAE format (+971XXXXXXXXX)"
    }
  }
}
```

---

### Example 4: Numeric Range Validation (Custom Implementation)

**Step 1: Add range validation to code**

```python
# In validate_business_rules function
elif rule.get("type") == "range":
    try:
        # Convert value to number
        numeric_value = float(value)
        
        min_val = rule.get("min")
        max_val = rule.get("max")
        
        is_valid = True
        if min_val is not None and numeric_value < min_val:
            is_valid = False
        if max_val is not None and numeric_value > max_val:
            is_valid = False
        
        if not is_valid:
            violations.append(
                f"❌ {FRIENDLY_LABELS.get(field_name, field_name)}: "
                f"Value {numeric_value} is outside allowed range "
                f"[{min_val or 'any'} - {max_val or 'any'}]. "
                f"{rule.get('error_message', '')}"
            )
            validation_details[field_name] = {
                "status": "failed",
                "value": value,
                "numeric_value": numeric_value,
                "min": min_val,
                "max": max_val,
                "error": rule.get('error_message', '')
            }
        else:
            validation_details[field_name] = {
                "status": "passed",
                "value": value,
                "numeric_value": numeric_value
            }
    except ValueError:
        warnings.append(
            f"⚠️ {FRIENDLY_LABELS.get(field_name, field_name)}: "
            f"Cannot convert '{value}' to number"
        )
```

**Step 2: Use in config.json**

```json
{
  "validation_rules": {
    "amount": {
      "type": "range",
      "min": 1000,
      "max": 1000000,
      "error_message": "Amount must be between AED 1,000 and AED 1,000,000"
    },
    "validityDays": {
      "type": "range",
      "min": 30,
      "max": 365,
      "error_message": "Validity must be between 30 and 365 days"
    }
  }
}
```

---

### Example 5: Custom Function Validation

For complex validation logic, create a custom function:

```python
# In validate_business_rules function
elif rule.get("type") == "custom":
    validation_function = rule.get("function")
    
    # Define custom validation functions
    def validate_emirates_id(value):
        """Validate UAE Emirates ID format"""
        if not value or len(value) != 18:
            return False, "Emirates ID must be 18 digits"
        if not value.replace('-', '').isdigit():
            return False, "Emirates ID must contain only numbers"
        return True, "Valid Emirates ID format"
    
    def validate_trade_license(value):
        """Validate UAE Trade License format"""
        if not value or len(value) < 6:
            return False, "Trade License number too short"
        # Add more validation logic
        return True, "Valid Trade License"
    
    # Map function names to actual functions
    validators = {
        "validate_emirates_id": validate_emirates_id,
        "validate_trade_license": validate_trade_license
    }
    
    if validation_function in validators:
        validator = validators[validation_function]
        is_valid, message = validator(value)
        
        if not is_valid:
            violations.append(
                f"❌ {FRIENDLY_LABELS.get(field_name, field_name)}: {message}"
            )
            validation_details[field_name] = {
                "status": "failed",
                "value": value,
                "error": message
            }
        else:
            validation_details[field_name] = {
                "status": "passed",
                "value": value,
                "message": message
            }
```

**Use in config.json:**

```json
{
  "validation_rules": {
    "emiratesId": {
      "type": "custom",
      "function": "validate_emirates_id",
      "error_message": "Invalid Emirates ID format"
    },
    "tradeLicense": {
      "type": "custom",
      "function": "validate_trade_license"
    }
  }
}
```

---

## Best Practices

### 1. Error Messages

Always provide clear, actionable error messages:

```json
{
  "issueDate": {
    "type": "date_age",
    "max_age_months": 6,
    "error_message": "Document issued more than 6 months ago. Please submit a recent NOC."
  }
}
```

### 2. Combine Multiple Rules

You can validate the same field with multiple rules by using different field names:

```json
{
  "validation_rules": {
    "issueDate_age": {
      "type": "date_age",
      "max_age_months": 6
    },
    "issueDate_format": {
      "type": "regex",
      "pattern": "^\\d{2}/\\d{2}/\\d{4}$"
    }
  }
}
```

### 3. Testing Strategy

1. **Test with valid data** - Ensure rules pass when they should
2. **Test with invalid data** - Ensure rules fail appropriately
3. **Test edge cases** - Dates on boundaries, empty values, etc.
4. **Check error messages** - Ensure they're clear and helpful

### 4. Performance Considerations

- Keep validation rules simple and fast
- Avoid complex regex patterns that could cause slowdowns
- Consider caching validation results if needed

---

## Troubleshooting

### Issue: Validation not running

**Solution:** Ensure "Enable business rule validation" checkbox is checked before uploading.

### Issue: Dates not parsing correctly

**Solution:** The `python-dateutil` library is flexible, but if dates aren't parsing:
1. Check the date format in extracted values
2. Add explicit date format handling in code
3. Use regex validation as a fallback

### Issue: Whitelist fuzzy matching too permissive

**Solution:** 
1. Set `fuzzy_match: false` for exact matching
2. Set `case_sensitive: true` if needed
3. Add more specific values to whitelist

### Issue: Custom validation not working

**Solution:**
1. Check for Python syntax errors in validation code
2. Ensure function is properly defined before use
3. Add try-catch blocks for error handling
4. Check logs for detailed error messages

---

## Complete Example Configuration

```json
{
  "version": "2.0.0",
  "port": 7070,
  "host": "0.0.0.0",
  "debug": false,
  
  "mandatory_fields": [
    "applicationNumber",
    "issuingAuthority",
    "ownerName",
    "issueDate"
  ],
  
  "field_weights": {
    "applicationNumber": 0.25,
    "issuingAuthority": 0.25,
    "ownerName": 0.25,
    "issueDate": 0.25
  },
  
  "validation_rules": {
    "issueDate": {
      "type": "date_age",
      "max_age_months": 6,
      "error_message": "NOC must be issued within the last 6 months"
    },
    "issuingAuthority": {
      "type": "whitelist",
      "allowed_values": [
        "Dubai Municipality",
        "Abu Dhabi DED",
        "Sharjah Municipality",
        "Ajman Municipality",
        "RAK Municipality",
        "Fujairah Municipality",
        "UAQ Municipality"
      ],
      "case_sensitive": false,
      "fuzzy_match": true,
      "error_message": "Issuing authority must be from approved UAE government entities"
    },
    "documentStatus": {
      "type": "whitelist",
      "allowed_values": ["Approved", "Active", "Valid"],
      "case_sensitive": false,
      "error_message": "Document status must be Approved, Active, or Valid"
    }
  },
  
  "approval_threshold": 0.85,
  "review_threshold": 0.6,
  "max_poll_attempts": 60,
  "poll_interval": 2,
  "max_pages_per_chunk": 10
}
```

---

## Summary

The validation system is highly extensible. To add new rules:

1. **Simple rules**: Just add to `config.json`
2. **Complex rules**: Add logic to `validate_business_rules` function
3. **Custom validators**: Create functions and map them in code

All validation results are:
- Logged in real-time
- Displayed in the Analysis Report
- Used to adjust document approval status
- Stored in job results for audit trails

For questions or issues, refer to the application logs or contact the development team.
