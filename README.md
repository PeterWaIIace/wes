# Git Task Runner

A Python utility that reads a JSON configuration, clones git repositories, executes commands, and cleans up.

## Features

- Reads task configuration from JSON file
- Clones git repositories using git command
- Executes arbitrary shell commands in specified paths
- Automatically removes cloned repositories after execution
- Error handling and detailed output

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

### Optional: Git Credentials

For HTTPS repositories that require authentication, create a `.env` file with credentials:

```bash
cp .env.example .env
```

Then edit `.env` and add your credentials:

```
GIT_USERNAME=your_github_username
GIT_PASSWORD=your_github_token_or_password
```

**Note:** Use a personal access token instead of your actual password for security.

## Usage

Run with default config file (`tasks.json`):
```bash
python main.py
```

Or specify a custom config file:
```bash
python main.py path/to/config.json
```

## JSON Configuration Format

```json
{
  "tasks": [
    {
      "git_url": "https://github.com/user/repo.git",
      "path": "src",
      "command": "ls -la"
    }
  ]
}
```

### Fields

- **git_url**: Full URL to the git repository (with or without `.git` suffix)
- **path**: Path within the repository where the command should be executed (relative to repo root)
- **command**: Shell command to execute in that directory

## Example

See `tasks.json` for a working example with common use cases.
