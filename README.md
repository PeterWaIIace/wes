# Git Task Runner

A Python utility that reads a `.wes` configuration, clones git repositories, executes commands, and cleans up.

## Features

- Reads task configuration from `.wes` file
- Clones git repositories using git command
- Executes arbitrary shell commands in specified paths
- Automatically removes cloned repositories after execution
- Error handling and detailed output

## Installation

```bash
pip install -r requirements.txt
```

Install development tools:

```bash
pip install -e ".[dev]"
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

Run with a `.wes` config file:
```bash
wes task.wes
```

Or via make:
```bash
make run
```

## Formatting and Linting

Check and auto-fix style issues:

```bash
ruff check . --fix
```

Format code:

```bash
ruff format .
```

## WES Configuration Format

The `.wes` format is YAML-based.

```yaml
sequence:
  - my_task_name:
      git_url: https://github.com/user/repo.git
      path: src
      command: ls -la
```

### Fields

- **task root name**: A unique key for each task (for example `my_task_name`)
- **git_url**: Full URL to the git repository (with or without `.git` suffix)
- **path**: Path within the repository where the command should be executed (relative to repo root)
- **command**: Shell command to execute in that directory

## Example

See `task.wes` for a working example with common use cases.

## Frontend Architecture

The web UI uses vanilla HTML/CSS/JS with Web Components for encapsulation. Each component lives in its own directory with separate files:

```
web/static/components/
  base/WesComponent.js         ← base class with template loading + helpers
  index.js                     ← imports all components
  component-name/
    component-name.html        ← markup
    component-name.css         ← scoped styles (shadow DOM)
    component-name.js          ← class extends HTMLElement
```

Components:

- **base** — `WesComponent` base class (template fetch, shadow DOM, event helpers)
- **time-chips** — time preset buttons (30m, 1h, 2h, 4h, 8h, 24h, 2d, 7d)
- **resource-slider** — labeled range slider (CPU, GPU, MEM)
- **chip-select** — filterable chip buttons (partition selector)
- **node-card** — cluster node card with capacity bars
- **jobs-table** — SLURM jobs table
- **task-tile** — dashboard task card (name, status, resources, actions)
- **cluster-panel** — SSH query + node grid + jobs table (dashboard)
- **config-panel** — task config form (memory, CPU, GPU, time, git, etc.)
- **log-viewer** — tabbed log panel (stdout, stderr, pre-run)
- **artifact-list** — videos, models, images, data files
- **settings-list** — removable item list
- **slurm-designer** — full SLURM job designer page
