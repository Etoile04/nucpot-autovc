"""NucPot AutoVC entry point."""

def main() -> None:
    """Start the AutoVC API server."""
    import uvicorn
    uvicorn.run("autovc.api:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
