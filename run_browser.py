from fieldbook_sync.app import run_server
from surveysync.router import restore_last_project

if __name__ == "__main__":
    restore_last_project()
    run_server(open_browser=True)
