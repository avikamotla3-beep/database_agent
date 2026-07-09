#!/usr/bin/env python3
"""
Main entry point for DB Agent.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_agent.orchestrator import Orchestrator


def main():
    print("=" * 60)
    print("DATABASE AGENT")
    print("=" * 60)
    
    orchestrator = Orchestrator()
    
    print("\nAvailable tools:")
    for name, tool in orchestrator.tools.items():
        print(f"  - {name}: {tool.schema['description'][:60]}...")
    
    print("\nEnter your query (or 'quit'):\n")
    
    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        
        if query.lower() in ("quit", "exit", "q"):
            break
        if not query:
            continue
        
        print("\n" + "-" * 60)
        
        try:
            result = orchestrator.run(query)
            
            print(f"\n[Decision] {result['decision']['reasoning']}")
            print(f"[Tool] {result['decision'].get('tool', 'direct')}")
            
            if result['tool_result']:
                print(f"\n[Tool Output]\n{result['tool_result'][:500]}")
                if len(result['tool_result']) > 500:
                    print("...")
            
            print(f"\n[Answer]\n{result['final_answer']}")
            
        except Exception as e:
            print(f"\n[ERROR] {str(e)}")
        
        print("-" * 60 + "\n")


if __name__ == "__main__":
    main()