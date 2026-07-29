from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from PyBPM!"}

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

if __name__ == "__main__":
    main()
