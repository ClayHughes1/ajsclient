import ollama

def run_agent(user_goal):
    # The system prompt defines the agent's persona and rules
    system_instruction = (
        "You are a helpful, concise local AI agent. "
        "Provide direct answers and step-by-step solutions."
    )
    
    print("🤖 Agent is thinking...")
    
    try:
        response = ollama.chat(
            model='llama3.2',
            messages=[
                {'role': 'system', 'content': system_instruction},
                {'role': 'user', 'content': user_goal}
            ]
        )
        
        # Extract and display the agent's response
        agent_response = response['message']['content']
        print("\n🤖 Agent Response:")
        print(agent_response)
        
    except Exception as e:
        print(f"\n Error connecting to Ollama: {e}")
        print("Make sure the Ollama icon is running in your Windows System Tray.")

if __name__ == "__main__":
    # Test your local agent
    prompt = "Write a quick 3-step checklist to verify a local database connection."
    run_agent(prompt)