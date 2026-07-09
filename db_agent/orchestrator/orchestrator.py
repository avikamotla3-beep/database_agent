import json
from typing import Dict, Any, Optional

from ..llm import LLMAdapter, OpenRouterAdapter
from ..tools import TOOL_INSTANCES


class Orchestrator:
    """
    Receives user query → analyzes → picks tool + model → executes → synthesizes answer.
    """
    
    def __init__(self, adapter: Optional[LLMAdapter] = None):
        self.adapter = adapter or OpenRouterAdapter()
        self.tools = TOOL_INSTANCES
    
    def _build_tools_description(self) -> str:
        """Build prompt section describing all tools."""
        lines = []
        for name, tool in self.tools.items():
            s = tool.schema
            lines.append(f"\nTOOL: {s['name']}")
            lines.append(f"  Description: {s['description']}")
            lines.append(f"  Capability: {s['capability']}")
            lines.append(f"  Parameters: {json.dumps(s['parameters'])}")
        return "\n".join(lines)
    
    def analyze(self, query: str) -> Dict[str, Any]:
        """
        Step 1: Analyze query, pick tool and model.
        """
        tools_desc = self._build_tools_description()
        
        system_prompt = f"""You are an orchestrator for a database agent.

{tools_desc}

Analyze the user's query and respond with ONLY this JSON format:
{{
    "requires_tool": true/false,
    "tool": "tool_name",
    "reasoning": "why this tool fits",
    "capability": "sql|graph|vector|schema|simple"
}}

Rules:
- Schema questions → describe_schema
- SQL, data retrieval → mysql_query
- Table relationships, connections → neo4j_query
- Finding tables by meaning, semantic search → pinecone_query
- General chat → requires_tool: false
"""
        
        response = self.adapter.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: {query}"}
            ],
            temperature=0.1
        )
        
        # Parse JSON from response
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            return self._fallback_analyze(query)
    
    def _fallback_analyze(self, query: str) -> Dict[str, Any]:
        """Keyword fallback when LLM fails."""
        q = query.lower()
        if any(w in q for w in ["schema", "table", "column", "describe", "structure"]):
            return {"requires_tool": True, "tool": "describe_schema", "reasoning": "Schema keywords", "capability": "schema"}
        elif any(w in q for w in ["sql", "select", "where", "join", "count", "from", "data"]):
            return {"requires_tool": True, "tool": "mysql_query", "reasoning": "SQL keywords", "capability": "sql"}
        elif any(w in q for w in ["neo4j", "graph", "relationship", "path", "connect", "related"]):
            return {"requires_tool": True, "tool": "neo4j_query", "reasoning": "Graph keywords", "capability": "graph"}
        elif any(w in q for w in ["similar", "semantic", "vector", "search", "find", "relevant"]):
            return {"requires_tool": True, "tool": "pinecone_query", "reasoning": "Vector keywords", "capability": "vector"}
        else:
            return {"requires_tool": False, "tool": None, "reasoning": "General query", "capability": "simple"}
    
    def generate_params(self, query: str, tool_name: str, capability: str) -> Dict[str, Any]:
        """
        Step 2: Ask LLM to generate tool parameters.
        """
        tool = self.tools[tool_name]
        schema = tool.schema
        
        prompt = f"""Generate parameters for this tool based on the user query.

Tool: {schema['name']}
Description: {schema['description']}
Parameters: {json.dumps(schema['parameters'])}

User Query: {query}

Respond with ONLY a JSON object containing the parameters. No explanation."""
        
        model = self.adapter.get_model_for_task(capability) if hasattr(self.adapter, 'get_model_for_task') else None
        
        response = self.adapter.chat(
            messages=[
                {"role": "system", "content": "Generate tool parameters as JSON only."},
                {"role": "user", "content": prompt}
            ],
            model=model,
            temperature=0.1
        )
        
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            return self._fallback_params(tool_name, query)
    
    def _fallback_params(self, tool_name: str, query: str) -> Dict[str, Any]:
        """Infer parameters from query when LLM fails."""
        if tool_name == "mysql_query":
            return {"query": query}
        elif tool_name == "neo4j_query":
            return {"query_type": "neighbors", "table": query.split()[-1]}
        elif tool_name == "pinecone_query":
            return {"query": query, "search_type": "all"}
        elif tool_name == "describe_schema":
            words = query.split()
            for w in words:
                if w.isalnum() and len(w) > 2:
                    return {"table_name": w}
            return {}
        return {}
    
    def synthesize(self, query: str, tool_result: str, tool_name: str) -> str:
        """
        Step 3: Synthesize final answer from tool result.
        """
        prompt = f"""User asked: {query}

Tool '{tool_name}' returned:
{tool_result[:2000]}

Provide a clear, helpful answer. If there was an error, explain what went wrong."""
        
        capability = self.tools[tool_name].schema["capability"] if tool_name else "simple"
        model = self.adapter.get_model_for_task(capability) if hasattr(self.adapter, 'get_model_for_task') else None
        
        response = self.adapter.chat(
            messages=[
                {"role": "system", "content": "Synthesize tool results into clear answers."},
                {"role": "user", "content": prompt}
            ],
            model=model,
            temperature=0.3
        )
        
        return response.content
    
    def direct_answer(self, query: str) -> str:
        """Answer without tools."""
        response = self.adapter.chat(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": query}
            ],
            temperature=0.7
        )
        return response.content
    
    def run(self, query: str) -> Dict[str, Any]:
        """Full pipeline: analyze → execute → synthesize."""
        # Step 1: Analyze
        decision = self.analyze(query)
        
        result = {
            "query": query,
            "decision": decision,
            "tool_result": None,
            "final_answer": None
        }
        
        if not decision.get("requires_tool"):
            result["final_answer"] = self.direct_answer(query)
            return result
        
        # Step 2: Generate params and execute
        tool_name = decision["tool"]
        params = self.generate_params(query, tool_name, decision["capability"])
        
        tool = self.tools[tool_name]
        tool_result = tool.run(**params)
        result["tool_result"] = tool_result
        
        # Step 3: Synthesize
        result["final_answer"] = self.synthesize(query, tool_result, tool_name)
        
        return result