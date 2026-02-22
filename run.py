from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug=True makes the server restart automatically when changes are saved
    app.run(debug=True)