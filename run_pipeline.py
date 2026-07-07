#!/usr/bin/env python3
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "CORE ORCHESTRATOR"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import asyncio
from dotenv import load_dotenv
load_dotenv()

from orchestrator import DBOrchestrator


async def main():
    orch = DBOrchestrator(
        state_dir="./pipeline_state",
        output_dir="./output"
    )
    
    print("=" * 60)
    print("RUNNING FULL PIPELINE")
    print("=" * 60)
    
    state = await orch.run_full_pipeline(
        dump_path="./Dump20260412 (1).sql",
        resume=True
    )
    
    print(f"\nPipeline complete!")
    print(f"  Run ID: {state.run_id}")
    print(f"  Schema: {state.schema_path}")
    print(f"  Described: {state.described_schema_path}")
    print(f"  Pinecone Index: {state.pinecone_index_name}")
    print(f"  Neo4j Graph: {state.neo4j_graph_id}")
    
    print("\n" + "=" * 60)
    print("READY FOR QUERIES")
    print("=" * 60)
    
    while True:
        question = input("\nAsk a question (or 'quit'): ").strip()
        if question.lower() in ('quit', 'exit', 'q'):
            break
        result = await orch.query(question, execute=True)
        print(f"\n  SQL: {result['sql']}")
        print(f"  Results: {result['results']}")
        print(f"  Explanation: {result['explanation']}")


if __name__ == "__main__":
    asyncio.run(main())
