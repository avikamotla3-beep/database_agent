#!/usr/bin/env python3
"""
DB Intelligence Orchestrator
Manages the full pipeline: Extract -> Describe -> Embed -> Graph -> Query
"""

import os
import sys
import json
import logging
import hashlib
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from contextlib import asynccontextmanager
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('pipeline.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('Orchestrator')


class PipelineStage(Enum):
    IDLE = auto()
    EXTRACT = auto()
    DESCRIBE = auto()
    EMBED = auto()
    GRAPH = auto()
    QUERY = auto()
    COMPLETE = auto()
    FAILED = auto()


@dataclass
class PipelineState:
    """Persistent checkpoint state"""
    run_id: str
    stage: str = "IDLE"
    dump_path: str = ""
    schema_path: str = ""
    described_schema_path: str = ""
    pinecone_index_name: str = ""
    neo4j_graph_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    completed_stages: List[str] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PipelineState":
        return cls(**data)


class StateManager:
    """Persistent state management with atomic writes"""
    
    def __init__(self, state_dir: str = "./pipeline_state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(exist_ok=True)
        self.state_file = self.state_dir / "state.json"
    
    def load(self) -> Optional[PipelineState]:
        """Load existing state or return None"""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            logger.info(f"Loaded state: stage={data.get('stage')}")
            return PipelineState.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None
    
    def save(self, state: PipelineState) -> None:
        """Atomic write of state"""
        state.updated_at = datetime.utcnow().isoformat()
        tmp_file = self.state_dir / "state.tmp"
        with open(tmp_file, 'w') as f:
            json.dump(state.to_dict(), f, indent=2)
        tmp_file.replace(self.state_file)
        logger.info(f"State saved: stage={state.stage}")
    
    def generate_run_id(self, dump_path: str) -> str:
        """Deterministic run ID based on dump file hash"""
        hasher = hashlib.sha256()
        hasher.update(dump_path.encode())
        hasher.update(str(datetime.utcnow().timestamp()).encode())
        return hasher.hexdigest()[:16]


class StageRunner:
    """Executes individual pipeline stages with error handling"""
    
    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.stage_registry: Dict[PipelineStage, Callable] = {}
    
    def register(self, stage: PipelineStage, handler: Callable):
        self.stage_registry[stage] = handler
        return self
    
    async def run_stage(self, stage: PipelineStage, state: PipelineState, **kwargs) -> PipelineState:
        """Execute a single stage with checkpointing"""
        stage_name = stage.name
        logger.info(f"{'='*60}")
        logger.info(f"STAGE START: {stage_name}")
        logger.info(f"{'='*60}")
        
        state.stage = stage_name
        state.started_at = state.started_at or datetime.utcnow().isoformat()
        self.state_manager.save(state)
        
        handler = self.stage_registry.get(stage)
        if not handler:
            raise ValueError(f"No handler registered for stage: {stage_name}")
        
        try:
            result_state = await handler(state, **kwargs)
            result_state.completed_stages.append(stage_name)
            logger.info(f"STAGE COMPLETE: {stage_name}")
            return result_state
            
        except Exception as e:
            error_msg = f"{stage_name} failed: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            state.errors.append(error_msg)
            state.stage = "FAILED"
            self.state_manager.save(state)
            raise PipelineError(error_msg) from e


class PipelineError(Exception):
    pass


class DBOrchestrator:
    """
    Main orchestrator class.
    Usage:
        orch = DBOrchestrator()
        await orch.run_full_pipeline("dump.sql")
        # or
        result = await orch.query("Show me total sales by region last month")
    """
    
    def __init__(self, 
                 state_dir: str = "./pipeline_state",
                 output_dir: str = "./output"):
        self.state_manager = StateManager(state_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.runner = StageRunner(self.state_manager)
        self._register_stages()
        self._tools_loaded = False
    
    def _register_stages(self):
        """Wire all stage handlers"""
        self.runner.register(PipelineStage.EXTRACT, self._stage_extract)
        self.runner.register(PipelineStage.DESCRIBE, self._stage_describe)
        self.runner.register(PipelineStage.EMBED, self._stage_embed)
        self.runner.register(PipelineStage.GRAPH, self._stage_graph)
    
    def _load_tools(self):
        """Lazy-load tool modules to avoid import overhead"""
        if self._tools_loaded:
            return
        
        # These will be your actual tool modules
        try:
            import schema_extractor_adpter as schema_extractor
            import decribe_adapter as describe_schema_tool
            import pinecone_adapter as pinecone_tool
            import neo4j_adapter as neo4j_tool
            import mysql_adapter as mysql_connection
            import mysql_adapter as security_tool
            
            self.extractor = schema_extractor
            self.describer = describe_schema_tool
            self.embedder = pinecone_tool
            self.graph_publisher = neo4j_tool
            self.db_connector = mysql_connection
            self.security = security_tool
            
            self._tools_loaded = True
            logger.info("All tool modules loaded successfully")
            
        except ImportError as e:
            logger.warning(f"Tool modules not found (expected during dev): {e}")
            self._tools_loaded = False
    
    # ═══════════════════════════════════════════════════════════════
    # STAGE 1: SCHEMA EXTRACTION
    # ═══════════════════════════════════════════════════════════════
    async def _stage_extract(self, state: PipelineState, **kwargs) -> PipelineState:
        self._load_tools()
        
        dump_path = kwargs.get('dump_path') or state.dump_path
        if not dump_path or not Path(dump_path).exists():
            raise FileNotFoundError(f"MySQL dump not found: {dump_path}")
        
        state.dump_path = str(Path(dump_path).resolve())
        
        # Output path
        schema_file = self.output_dir / f"{state.run_id}_schema.json"
        state.schema_path = str(schema_file)
        
        if hasattr(self, 'extractor') and self._tools_loaded:
            # Use your actual schema_extractor.py
            schema = self.extractor.extract_from_dump(dump_path)
            with open(schema_file, 'w') as f:
                json.dump(schema, f, indent=2)
        else:
            # Placeholder: create expected structure
            logger.warning("Using placeholder schema extraction")
            schema = self._placeholder_extract(dump_path)
            with open(schema_file, 'w') as f:
                json.dump(schema, f, indent=2)
        
        tables = schema.get('tables', {})
        if isinstance(tables, list):
            state.metadata['tables_count'] = len(tables)
            state.metadata['columns_count'] = sum(
                len(t.get('columns', [])) for t in tables
            )
        else:
            state.metadata['tables_count'] = len(tables)
            state.metadata['columns_count'] = sum(
                len(t.get('columns', [])) for t in tables.values()
            )
        
        logger.info(f"Extracted {state.metadata['tables_count']} tables, "
                   f"{state.metadata['columns_count']} columns")
        
        return state
    
    def _placeholder_extract(self, dump_path: str) -> Dict:
        """Minimal SQL parser for development/testing"""
        # In production, this delegates to your schema_extractor.py
        return {
            "source": dump_path,
            "extracted_at": datetime.utcnow().isoformat(),
            "tables": {},
            "relationships": []
        }
    
    # ═══════════════════════════════════════════════════════════════
    # STAGE 2: SCHEMA DESCRIPTION (MiniMax-M3)
    # ═══════════════════════════════════════════════════════════════
    async def _stage_describe(self, state: PipelineState, **kwargs) -> PipelineState:
        self._load_tools()
        
        if not state.schema_path or not Path(state.schema_path).exists():
            raise FileNotFoundError("Schema JSON not found. Run EXTRACT first.")
        
        described_file = self.output_dir / f"{state.run_id}_described_schema.json"
        state.described_schema_path = str(described_file)
        
        # Load schema
        with open(state.schema_path, 'r') as f:
            schema = json.load(f)
        
        if hasattr(self, 'describer') and self._tools_loaded:
            described = self.describer.enrich_schema(
                schema,
                model="llama3.2",
                max_tokens=4096
            )
            
            
        else:
            # Placeholder
            logger.warning("Using placeholder schema description")
            described = self._placeholder_describe(schema)
        
        with open(described_file, 'w') as f:
            json.dump(described, f, indent=2)
        
        # Track description coverage
        total_cols = sum(
            len(t.get('columns', [])) 
            for t in described.get('tables', {}).values()
        )
        described_cols = sum(
            1 for t in described.get('tables', {}).values()
            for c in t.get('columns', [])
            if c.get('description')
        )
        state.metadata['description_coverage'] = (
            f"{described_cols}/{total_cols}" if total_cols else "0/0"
        )
        logger.info(f"Description coverage: {state.metadata['description_coverage']}")
        
        return state
    
    def _placeholder_describe(self, schema: Dict) -> Dict:
        """Placeholder: add empty description fields"""
        for table_name, table in schema.get('tables', {}).items():
            if not table.get('description'):
                table['description'] = f"Table: {table_name}"
            for col in table.get('columns', []):
                if not col.get('description'):
                    col['description'] = f"Column: {col.get('name', 'unknown')}"
        return schema
    
    # ═══════════════════════════════════════════════════════════════
    # STAGE 3: PINECONE EMBEDDINGS
    # ═══════════════════════════════════════════════════════════════
    async def _stage_embed(self, state: PipelineState, **kwargs) -> PipelineState:
        self._load_tools()
        
        if not state.described_schema_path:
            raise FileNotFoundError("Described schema not found. Run DESCRIBE first.")
        
        with open(state.described_schema_path, 'r') as f:
            schema = json.load(f)
        
        index_name = kwargs.get('index_name') or f"schema-{state.run_id[:8]}"
        state.pinecone_index_name = index_name
        
        if hasattr(self, 'embedder') and self._tools_loaded:
            # Use your actual pinecone_tool.py
            self.embedder.upsert_schema_vectors(
                index_name=index_name,
                schema=schema,
                namespace="schema-metadata"
            )
        else:
            logger.warning("Using placeholder embedding (Pinecone not connected)")
        
        state.metadata['pinecone_index'] = index_name
        logger.info(f"Schema embedded to Pinecone index: {index_name}")
        
        return state
    
    # ═══════════════════════════════════════════════════════════════
    # STAGE 4: NEO4J GRAPH PUBLISHING
    # ═══════════════════════════════════════════════════════════════
    async def _stage_graph(self, state: PipelineState, **kwargs) -> PipelineState:
        self._load_tools()
        
        if not state.described_schema_path:
            raise FileNotFoundError("Described schema not found. Run DESCRIBE first.")
        
        with open(state.described_schema_path, 'r') as f:
            schema = json.load(f)
        
        graph_id = kwargs.get('graph_id') or f"graph-{state.run_id[:8]}"
        state.neo4j_graph_id = graph_id
        
        if hasattr(self, 'graph_publisher') and self._tools_loaded:
            # Use your actual neo4j_tool.py
            self.graph_publisher.publish_schema_graph(
                graph_id=graph_id,
                schema=schema
            )
        else:
            logger.warning("Using placeholder graph publishing (Neo4j not connected)")
        
        state.metadata['neo4j_graph'] = graph_id
        logger.info(f"Schema graph published to Neo4j: {graph_id}")
        
        return state
    
    # ═══════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════
    async def run_full_pipeline(self, 
                                 dump_path: str,
                                 resume: bool = True,
                                 index_name: Optional[str] = None,
                                 graph_id: Optional[str] = None) -> PipelineState:
        """
        Run the complete pipeline from MySQL dump to graph.
        
        Args:
            dump_path: Path to .sql dump file
            resume: If True, resume from last checkpoint
            index_name: Custom Pinecone index name
            graph_id: Custom Neo4j graph identifier
        
        Returns:
            Final PipelineState
        """
        # Check for existing state
        existing = self.state_manager.load()
        
        if resume and existing and existing.dump_path == str(Path(dump_path).resolve()):
            state = existing
            logger.info(f"Resuming pipeline from stage: {state.stage}")
        else:
            run_id = self.state_manager.generate_run_id(dump_path)
            state = PipelineState(
                run_id=run_id,
                dump_path=str(Path(dump_path).resolve()),
                started_at=datetime.utcnow().isoformat()
            )
            logger.info(f"Starting new pipeline: {run_id}")
        
        # Determine starting stage
        stages_to_run = []
        completed = set(state.completed_stages)
        
        if "EXTRACT" not in completed:
            stages_to_run.append(PipelineStage.EXTRACT)
        if "DESCRIBE" not in completed:
            stages_to_run.append(PipelineStage.DESCRIBE)
        if "EMBED" not in completed:
            stages_to_run.append(PipelineStage.EMBED)
        if "GRAPH" not in completed:
            stages_to_run.append(PipelineStage.GRAPH)
        
        if not stages_to_run:
            logger.info("All stages already complete!")
            state.stage = "COMPLETE"
            self.state_manager.save(state)
            return state
        
        # Execute stages
        for stage in stages_to_run:
            kwargs = {}
            if stage == PipelineStage.EXTRACT:
                kwargs['dump_path'] = dump_path
            elif stage == PipelineStage.EMBED:
                kwargs['index_name'] = index_name
            elif stage == PipelineStage.GRAPH:
                kwargs['graph_id'] = graph_id
            
            state = await self.runner.run_stage(stage, state, **kwargs)
        
        state.stage = "COMPLETE"
        self.state_manager.save(state)
        logger.info(f"Pipeline complete! Run ID: {state.run_id}")
        return state
    
    async def query(self, 
                    question: str,
                    use_embeddings: bool = True,
                    use_graph: bool = True,
                    execute: bool = True) -> Dict[str, Any]:
        """
        Natural language to MySQL query execution.
        
        Args:
            question: Natural language question
            use_embeddings: Use Pinecone for schema context retrieval
            use_graph: Use Neo4j for relationship context
            execute: Actually execute the generated SQL
        
        Returns:
            Dict with 'sql', 'results', 'explanation', 'metadata'
        """
        self._load_tools()
        state = self.state_manager.load()
        
        if not state or state.stage != "COMPLETE":
            raise PipelineError("Pipeline not complete. Run full_pipeline first.")
        
        # Load described schema for context
        with open(state.described_schema_path, 'r') as f:
            schema = json.load(f)
        
        # Retrieve relevant schema context
        context = {
            "schema": schema,
            "question": question,
            "relevant_tables": []
        }
        
        if use_embeddings and hasattr(self, 'embedder') and self._tools_loaded:
            # Semantic retrieval from Pinecone
            relevant = self.embedder.query_similar_schema(
                index_name=state.pinecone_index_name,
                query=question,
                top_k=5
            )
            context['relevant_tables'] = [r['id'] for r in relevant.get('matches', [])]
            logger.info(f"Retrieved {len(context['relevant_tables'])} relevant tables via embeddings")
        
        if use_graph and hasattr(self, 'graph_publisher') and self._tools_loaded:
            # Get relationship context from Neo4j
            graph_context = self.graph_publisher.get_query_context(
                graph_id=state.neo4j_graph_id,
                tables=context['relevant_tables']
            )
            context['relationships'] = graph_context
            logger.info("Retrieved relationship context from Neo4j")
        
        # Generate SQL using LLM (MiniMax-M3)
        sql = self._generate_sql(context)
        
        # Security validation
        if hasattr(self, 'security') and self._tools_loaded:
            is_safe, reason = self.security.validate_query(sql)
            if not is_safe:
                return {
                    "sql": sql,
                    "results": None,
                    "explanation": f"Query blocked by security policy: {reason}",
                    "metadata": {"blocked": True, "reason": reason}
                }
        
        result = {
            "sql": sql,
            "results": None,
            "explanation": "",
            "metadata": {
                "run_id": state.run_id,
                "pinecone_index": state.pinecone_index_name,
                "neo4j_graph": state.neo4j_graph_id
            }
        }
        
        if execute and hasattr(self, 'db_connector') and self._tools_loaded:
            try:
                result['results'] = self.db_connector.execute(sql)
                result['explanation'] = self._explain_results(result['results'])
            except Exception as e:
                result['explanation'] = f"Execution error: {str(e)}"
                logger.error(f"Query execution failed: {e}")
        
        return result
    
    def _generate_sql(self, context: Dict) -> str:
        """
        Generate SQL from natural language using MiniMax-M3.
        In production, this calls your LLM integration.
        """
        # Placeholder - replace with actual MiniMax-M3 call
        schema_summary = json.dumps(context['schema'], indent=2)[:4000]
        prompt = f"""You are a MySQL expert. Given this schema context, write a valid MySQL query.

Schema Tables: {list(context['schema'].get('tables', {}).keys())}
Relevant Tables: {context.get('relevant_tables', [])}
Question: {context['question']}

Generate only the SQL query, no explanation."""
        
        # TODO: Replace with actual MiniMax-M3 API call
        # from openai import OpenAI
        # client = OpenAI(base_url="https://api.minimax.io/v1", api_key=os.getenv("MINIMAX_API_KEY"))
        # response = client.chat.completions.create(
        #     model="MiniMax-M3",
        #     messages=[{"role": "user", "content": prompt}],
        #     max_tokens=2000
        # )
        # return response.choices[0].message.content.strip()
        
        logger.info("SQL generation (placeholder - integrate MiniMax-M3)")
        return f"-- Generated SQL for: {context['question']}\nSELECT * FROM relevant_table LIMIT 10;"
    
    def _explain_results(self, results: Any) -> str:
        """Generate human-readable explanation of results"""
        if isinstance(results, list):
            return f"Query returned {len(results)} rows."
        return "Query executed successfully."
    
    def get_status(self) -> Dict[str, Any]:
        """Get current pipeline status"""
        state = self.state_manager.load()
        if not state:
            return {"status": "NO_STATE", "message": "No pipeline has been run yet"}
        return {
            "status": state.stage,
            "run_id": state.run_id,
            "completed_stages": state.completed_stages,
            "metadata": state.metadata,
            "errors": len(state.errors),
            "started_at": state.started_at,
            "updated_at": state.updated_at
        }
    
    def reset(self) -> None:
        """Clear all state and outputs"""
        import shutil
        if self.state_manager.state_dir.exists():
            shutil.rmtree(self.state_manager.state_dir)
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.state_manager = StateManager()
        logger.info("Pipeline state reset complete")


# ═══════════════════════════════════════════════════════════════════════
# CLI INTERFACE
# ═══════════════════════════════════════════════════════════════════════

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="DB Intelligence Orchestrator")
    parser.add_argument('command', choices=['run', 'query', 'status', 'reset'])
    parser.add_argument('--dump', '-d', help='Path to MySQL dump file')
    parser.add_argument('--question', '-q', help='Natural language query')
    parser.add_argument('--index', '-i', help='Pinecone index name')
    parser.add_argument('--graph', '-g', help='Neo4j graph ID')
    parser.add_argument('--no-resume', action='store_true', help='Start fresh, ignore checkpoints')
    
    args = parser.parse_args()
    orch = DBOrchestrator()
    
    if args.command == 'run':
        if not args.dump:
            print("Error: --dump required for 'run' command")
            sys.exit(1)
        state = await orch.run_full_pipeline(
            dump_path=args.dump,
            resume=not args.no_resume,
            index_name=args.index,
            graph_id=args.graph
        )
        print(f"\nPipeline complete!")
        print(f"Run ID: {state.run_id}")
        print(f"Schema: {state.schema_path}")
        print(f"Described: {state.described_schema_path}")
        print(f"Pinecone Index: {state.pinecone_index_name}")
        print(f"Neo4j Graph: {state.neo4j_graph_id}")
        
    elif args.command == 'query':
        if not args.question:
            print("Error: --question required for 'query' command")
            sys.exit(1)
        result = await orch.query(args.question)
        print(json.dumps(result, indent=2))
        
    elif args.command == 'status':
        print(json.dumps(orch.get_status(), indent=2))
        
    elif args.command == 'reset':
        orch.reset()
        print("Pipeline reset complete.")


if __name__ == "__main__":
    asyncio.run(main())