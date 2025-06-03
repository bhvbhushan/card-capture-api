from typing import Callable, Any, Dict, List
from functools import wraps
from app.utils.retry_utils import log_debug
from contextlib import contextmanager

@contextmanager
def db_operation_context(supabase_client, operation_name: str = "Database operation"):
    """
    Context manager for handling database operations with proper error handling and logging.
    Note: This does NOT provide true transactions since Supabase doesn't support them.
    It only provides logging and error handling context.
    
    Usage:
        with db_operation_context(supabase_client, "Update user profile") as client:
            client.table("users").update({"name": "John"}).eq("id", user_id).execute()
            client.table("profiles").update({"updated_at": now}).eq("user_id", user_id).execute()
    
    Args:
        supabase_client: The Supabase client instance
        operation_name: Name of the operation for logging
    """
    try:
        log_debug(f"Starting database operation: {operation_name}", service="database")
        yield supabase_client
        log_debug(f"Database operation completed successfully: {operation_name}", service="database")
    except Exception as e:
        log_debug(f"Database operation failed: {operation_name}", {
            "error": str(e),
            "type": type(e).__name__
        }, service="database")
        raise

# Alias for backward compatibility
db_transaction = db_operation_context

def ensure_atomic_updates(tables: List[str]):
    """
    Decorator to ensure multiple table updates are atomic-like.
    Note: Since Supabase doesn't support real transactions, this provides
    error handling and logging context but NOT true atomicity.
    
    Args:
        tables: List of table names being updated
        
    Usage:
        @ensure_atomic_updates(["users", "profiles"])
        def update_user_profile(supabase_client, user_id: str, data: Dict):
            # Function implementation
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(supabase_client, *args, **kwargs):
            operation_name = f"{func.__name__} on tables {', '.join(tables)}"
            with db_operation_context(supabase_client, operation_name):
                return func(supabase_client, *args, **kwargs)
        return wrapper
    return decorator

def safe_db_operation(operation_name: str = "Database operation"):
    """
    Decorator for safely executing database operations with proper error handling.
    
    Usage:
        @safe_db_operation("Get user profile")
        def get_user(supabase_client, user_id: str):
            return supabase_client.table("users").select("*").eq("id", user_id).single().execute()
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(supabase_client, *args, **kwargs):
            try:
                result = func(supabase_client, *args, **kwargs)
                
                # Handle Supabase response
                if hasattr(result, 'data'):
                    if result.data is None:
                        log_debug(f"No data returned: {operation_name}", service="database")
                        return None
                    return result.data
                return result
                
            except Exception as e:
                log_debug(f"Database operation failed: {operation_name}", {
                    "error": str(e),
                    "type": type(e).__name__,
                    "args": str(args),
                    "kwargs": str(kwargs)
                }, service="database")
                raise
            
        return wrapper
    return decorator

def validate_db_response(response: Any, operation_name: str = "Database operation") -> bool:
    """
    Validates a database response and logs any issues.
    
    Args:
        response: The database response to validate
        operation_name: Name of the operation for logging
        
    Returns:
        bool: True if response is valid, False otherwise
    """
    if not response:
        log_debug(f"Empty response from database: {operation_name}", service="database")
        return False
        
    if hasattr(response, 'error') and response.error:
        log_debug(f"Database error in {operation_name}", {
            "error": str(response.error)
        }, service="database")
        return False
        
    if hasattr(response, 'data'):
        if response.data is None:
            log_debug(f"No data in response: {operation_name}", service="database")
            return False
            
        if isinstance(response.data, list) and len(response.data) == 0:
            log_debug(f"Empty data list in response: {operation_name}", service="database")
            return False
            
    return True

def handle_db_error(error: Exception, operation_name: str) -> Dict[str, Any]:
    """
    Standardized error handling for database operations.
    
    Args:
        error: The exception that occurred
        operation_name: Name of the operation for logging
        
    Returns:
        Dict with error details
    """
    error_type = type(error).__name__
    error_msg = str(error)
    
    # Log the error
    log_debug(f"Database error in {operation_name}", {
        "type": error_type,
        "message": error_msg
    }, service="database")
    
    # Categorize the error
    if "duplicate" in error_msg.lower():
        return {
            "error": "duplicate_entry",
            "message": "This record already exists",
            "details": error_msg
        }
    elif "foreign key" in error_msg.lower():
        return {
            "error": "foreign_key_violation",
            "message": "Referenced record does not exist",
            "details": error_msg
        }
    elif "not found" in error_msg.lower():
        return {
            "error": "not_found",
            "message": "Record not found",
            "details": error_msg
        }
    elif "permission" in error_msg.lower():
        return {
            "error": "permission_denied",
            "message": "You don't have permission to perform this operation",
            "details": error_msg
        }
    else:
        return {
            "error": "database_error",
            "message": "An unexpected database error occurred",
            "details": error_msg
        } 