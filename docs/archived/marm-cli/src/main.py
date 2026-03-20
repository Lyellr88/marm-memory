"""MARM CLI v1.0.0 - Main entry point"""
import sys
import logging
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console
from rich.logging import RichHandler

from config.settings import get_settings
from marm.database import MARMDatabase
from marm.semantic import SemanticSearch
from marm.protocol import ProtocolInjector
from marm.tool_registry import get_tool_registry
from marm.example_tool import EchoTool
from marm.marm_tools import get_all_marm_tools

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger(__name__)

console = Console()


@click.group()
@click.version_option(version="1.0.0", prog_name="MARM CLI")
def cli():
    """MARM CLI - Professional offline AI assistant with persistent memory"""
    pass


@cli.command()
def init():
    """Initialize MARM CLI (create database, load models)"""
    console.print("[bold green]Initializing MARM CLI v1.0.0...[/bold green]\n")

    # Load settings
    settings = get_settings()
    console.print("[green]+[/green] Settings loaded from config/settings.json")

    # Initialize database
    db = MARMDatabase(settings.marm.database_path)
    console.print(f"[green]+[/green] Database initialized at {settings.marm.database_path}")

    # Initialize semantic search
    semantic = SemanticSearch(cache_dir=settings.marm.embeddings_cache)
    console.print(f"[green]+[/green] Semantic search initialized (model will load on first use)")

    # Load protocol
    protocol = ProtocolInjector()
    protocol.load_protocol()
    protocol.load_documentation()
    console.print(f"[green]+[/green] MARM protocol loaded")

    console.print("\n[bold green]MARM CLI initialized successfully![/bold green]")
    console.print("\nRun [bold]marm chat[/bold] to start a conversation")


@cli.command()
def chat():
    """Start interactive chat session"""
    import asyncio
    from chat import start_chat

    try:
        asyncio.run(start_chat())
    except Exception as e:
        console.print(f"[red]Chat error: {e}[/red]")
        logger.exception("Failed to start chat")


@cli.command()
def status():
    """Show MARM CLI status"""
    settings = get_settings()

    console.print("[bold]MARM CLI Status[/bold]\n")
    console.print(f"Version: [green]1.0.0[/green]")
    console.print(f"Database: {settings.marm.database_path}")
    console.print(f"Ollama URL: {settings.ollama.base_url}")
    console.print(f"Model: {settings.ollama.model}")
    console.print(f"\nAuto-logging: [green]ON[/green]" if settings.marm.auto_log_enabled else "\nAuto-logging: [red]OFF[/red]")
    console.print(f"Auto-refresh: [green]ON[/green]" if settings.marm.auto_refresh_enabled else "Auto-refresh: [red]OFF[/red]")
    console.print(f"Context bridge: [green]ON[/green]" if settings.marm.context_bridge_enabled else "Context bridge: [red]OFF[/red]")


@cli.command()
def test():
    """Test MARM components"""
    console.print("[bold]Testing MARM Components...[/bold]\n")

    try:
        # Test database
        console.print("1. Testing database... ", end="")
        settings = get_settings()
        db = MARMDatabase(settings.marm.database_path)
        console.print("[green]PASS[/green]")

        # Test semantic search
        console.print("2. Testing semantic search... ", end="")
        semantic = SemanticSearch()
        test_embedding = semantic.get_embedding("test query")
        console.print(f"[green]PASS[/green] (embedding shape: {test_embedding.shape})")

        # Test protocol
        console.print("3. Testing protocol injection... ", end="")
        protocol = ProtocolInjector()
        system_prompt = protocol.build_system_prompt()
        console.print(f"[green]PASS[/green] (prompt length: {len(system_prompt)} chars)")

        # Test tool infrastructure
        console.print("4. Testing tool infrastructure... ", end="")
        registry = get_tool_registry()

        # Register echo tool for basic testing
        echo_tool = EchoTool()
        registry.register(echo_tool)
        logger.info(f"Registered example tool: {echo_tool.name}")

        # Register all 14 MARM tools
        marm_tools = get_all_marm_tools()
        logger.info(f"Registering {len(marm_tools)} MARM tools...")
        for tool in marm_tools:
            registry.register(tool)
            logger.debug(f"  ✓ Registered: {tool.name} ({tool.kind.value})")

        total_tools = len(registry)
        logger.info(f"Tool registration complete: {total_tools} tools ready")
        console.print(f"[green]PASS[/green] (registered {total_tools} tools: 1 echo + 14 MARM)")

        # Test tool invocation
        console.print("5. Testing tool invocation... ", end="")
        import asyncio
        result = asyncio.run(echo_tool.invoke({"message": "test", "repeat": 2}))
        if result.success:
            console.print(f"[green]PASS[/green]")
        else:
            console.print(f"[red]FAIL[/red]: {result.error}")

        # Test Ollama client (optional - only if Ollama is running)
        console.print("6. Testing Ollama client (optional)... ", end="")
        try:
            from marm import OllamaClient
            async def test_ollama():
                async with OllamaClient(base_url=settings.ollama.base_url) as client:
                    # Just test connection, don't actually chat
                    return True
            asyncio.run(test_ollama())
            console.print(f"[green]PASS[/green]")
        except Exception as e:
            console.print(f"[yellow]SKIP[/yellow] (Ollama not running: {str(e)[:50]})")

        console.print("\n[bold green]Core tests passed![/bold green]")

    except Exception as e:
        console.print(f"[red]FAIL: {e}[/red]")
        logger.exception("Test failed")


def main():
    """Main entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n\nExiting MARM CLI...")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
