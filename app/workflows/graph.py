from langgraph.graph import StateGraph, END
from app.models.state import AgentState
from app.workflows import nodes

def build_graph():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("memory", nodes.load_memory_node)
    workflow.add_node("router", nodes.router_node)
    workflow.add_node("tools", nodes.tool_node)
    workflow.add_node("generator", nodes.generator_node)
    
    workflow.set_entry_point("memory")
    
    workflow.add_edge("memory", "router")
    
    def route_logic(state):
        i = state["intent"]
        if i in ["CHITCHAT", "ONBOARDING"]: return "generator"
        return "tools"
        
    workflow.add_conditional_edges("router", route_logic, {"tools": "tools", "generator": "generator"})
    workflow.add_edge("tools", "generator")
    workflow.add_edge("generator", END)
    
    return workflow.compile()