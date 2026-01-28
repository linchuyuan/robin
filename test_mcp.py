import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import sys
import shutil

async def test_server():
    # Detect python executable
    python_exe = sys.executable
    
    server_params = StdioServerParameters(
        command=python_exe,
        args=["server.py"],
        env=None
    )

    print("Connecting to MCP server...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize connection
            await session.initialize()
            print("Connected!")

            # List tools
            tools = await session.list_tools()
            print(f"\nFound {len(tools.tools)} tools:")
            for tool in tools.tools:
                print(f" - {tool.name}: {tool.description}")

            # Optional: Test a tool call (commented out to avoid side effects during simple check)
            # print("\nTesting get_stock_news...")
            # result = await session.call_tool("get_stock_news", arguments={"symbol": "AAPL"})
            # print(f"Result preview: {str(result.content)[:100]}...")

if __name__ == "__main__":
    # We need the 'mcp' package installed for the client too
    # If not installed, this will fail
    try:
        asyncio.run(test_server())
    except ImportError:
        print("Please install the 'mcp' package to run this test:")
        print("pip install mcp")
    except Exception as e:
        print(f"Error: {e}")
