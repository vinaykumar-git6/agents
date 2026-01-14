"""
Output Formatting Utilities
Helper functions for console output formatting with colors.
"""

from typing import Optional


# ============================================================================
# ANSI Color Constants
# ============================================================================

ANSI_COLORS = {
    'CYAN': '\033[96m',
    'YELLOW': '\033[93m',
    'GREEN': '\033[92m',
    'MAGENTA': '\033[95m',
    'BLUE': '\033[94m',
    'RED': '\033[91m',
    'BOLD': '\033[1m',
    'RESET': '\033[0m',
}


# ============================================================================
# Agent Output Logging
# ============================================================================

def log_agent_output(
    agent_name: str,
    output: str,
    color: str = 'CYAN',
    truncate_length: Optional[int] = 2000
) -> None:
    """
    Log agent output with consistent formatting and colors.
    
    Args:
        agent_name: Name of the agent producing output
        output: The output text to display
        color: Color key from ANSI_COLORS (default: 'CYAN')
        truncate_length: Max length before truncation (None to disable)
    """
    color_code = ANSI_COLORS.get(color, ANSI_COLORS['CYAN'])
    reset = ANSI_COLORS['RESET']
    bold = ANSI_COLORS['BOLD']
    
    # Create header
    header = f"{bold}{'=' * 80}{reset}"
    agent_header = f"{color_code}{bold}[{agent_name.upper()}]{reset}"
    separator = f"{bold}{'-' * 80}{reset}"
    
    # Truncate if needed
    display_output = output
    if truncate_length and len(output) > truncate_length:
        display_output = output[:truncate_length] + f"\n... [truncated {len(output) - truncate_length} chars]"
    
    # Print formatted output
    print(f"\n{header}")
    print(f"{agent_header} {color_code}Output:{reset}")
    print(separator)
    print(display_output)
    print(f"{header}\n")


def format_section_header(title: str, char: str = '=', width: int = 80) -> str:
    """
    Format a section header with decorative characters.
    
    Args:
        title: The title to display
        char: The character to use for decoration
        width: Total width of the header
        
    Returns:
        Formatted header string
    """
    bold = ANSI_COLORS['BOLD']
    reset = ANSI_COLORS['RESET']
    
    border = char * width
    padded_title = f" {title} ".center(width, char)
    
    return f"\n{bold}{border}{reset}\n{bold}{padded_title}{reset}\n{bold}{border}{reset}\n"


def print_status(message: str, status: str = 'INFO') -> None:
    """
    Print a status message with appropriate color.
    
    Args:
        message: The message to display
        status: Status type - 'INFO', 'SUCCESS', 'WARNING', 'ERROR'
    """
    color_map = {
        'INFO': 'CYAN',
        'SUCCESS': 'GREEN',
        'WARNING': 'YELLOW',
        'ERROR': 'RED'
    }
    
    symbol_map = {
        'INFO': 'ℹ',
        'SUCCESS': '✓',
        'WARNING': '⚠',
        'ERROR': '✗'
    }
    
    color = ANSI_COLORS.get(color_map.get(status, 'CYAN'), ANSI_COLORS['CYAN'])
    symbol = symbol_map.get(status, 'ℹ')
    reset = ANSI_COLORS['RESET']
    
    print(f"{color}{symbol} {message}{reset}")
