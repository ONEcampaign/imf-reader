# Contributing to imf-reader

Thank you for your interest in contributing to imf-reader! This guide will help you get started with contributing code, documentation, or bug reports.

## Ways to Contribute

### Report Bugs

Found a bug? Please report it on our [GitHub Issues](https://github.com/ONEcampaign/imf-reader/issues) page.

**Good bug reports include**:
- What you expected to happen
- What actually happened
- Steps to reproduce the issue
- Your Python version and imf-reader version
- Any error messages or logs

**Example**:
```
Title: NoDataError when fetching October 2025 WEO data

Description:
When I call weo.fetch_data(version=("October", 2025)), I get a NoDataError
even though the data should be available on the IMF website.

Steps to reproduce:
1. from imf_reader import weo
2. df = weo.fetch_data(version=("October", 2025))
3. Error: NoDataError: Could not fetch data for version: October 2025

Environment:
- Python 3.11.5
- imf-reader 1.3.0
- macOS 13.4
```

### Suggest Features

Have an idea for a new feature? Open an issue on GitHub with:
- Clear description of the feature
- Use case: what problem does it solve?
- Example of how you'd use it

### Improve Documentation

Documentation improvements are always welcome! This includes:
- Fixing typos or unclear explanations
- Adding examples for common use cases
- Improving code comments
- Writing tutorials or guides

You can edit documentation directly on GitHub by clicking the "Edit" button on any page, or submit a pull request.

### Contribute Code

We welcome code contributions! Here's how to get started.

## Development Setup

### 1. Fork and Clone

Fork the repository on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR-USERNAME/imf-reader.git
cd imf-reader
```

### 2. Set Up Development Environment

Install the package in development mode with all dependencies:

```bash
# Create a virtual environment
uv venv

# Activate it
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows

# Install in editable mode with dev dependencies
uv pip install -e ".[dev]"
```

This installs imf-reader in "editable" mode, so your changes are immediately reflected without reinstalling.

### 3. Create a Branch

Create a new branch for your work:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

Use descriptive branch names like:
- `feature/add-weo-regions`
- `fix/sdr-date-parsing`
- `docs/improve-quickstart`

## Making Changes

### Code Style

We use **Black** for code formatting. Run it before committing:

```bash
black src/imf_reader
```

### Testing

Run the test suite to ensure your changes don't break existing functionality:

```bash
pytest
```

Run tests with coverage:

```bash
pytest --cov=imf_reader --cov-report=term-missing
```

### Adding Tests

If you're adding new functionality, please include tests:

```python
# tests/test_your_feature.py
from imf_reader import weo

def test_your_new_feature():
    """Test description."""
    result = weo.your_new_function()
    assert result is not None
    # More assertions...
```

### Documentation

If you add new features or change existing behavior, update the documentation:

1. Update relevant `.md` files in `/docs`
2. Update docstrings in the code
3. Add examples showing how to use the new feature

## Submitting Changes

### 1. Commit Your Changes

Write clear, descriptive commit messages:

```bash
git add .
git commit -m "Add support for WEO regional aggregates

- Implement fetch_regional_data() function
- Add tests for regional data parsing
- Update documentation with regional examples"
```

**Good commit message**:
- First line: brief summary (50 chars or less)
- Blank line
- Detailed description if needed
- Reference issue numbers: "Fixes #123"

### 2. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 3. Open a Pull Request

Go to the [imf-reader repository](https://github.com/ONEcampaign/imf-reader) and open a pull request from your branch.

**Pull request template**:
```
## Description
Brief description of what this PR does.

## Changes
- Added X feature
- Fixed Y bug
- Updated Z documentation

## Testing
- [ ] Tests pass locally
- [ ] Added tests for new functionality
- [ ] Documentation updated

## Related Issues
Fixes #123
```

### 4. Code Review

Maintainers will review your PR and may request changes. This is a normal part of the process—we're collaborating to make the best possible code!

## Development Guidelines

### Keep PRs Focused

Submit separate PRs for different features or fixes. This makes review easier and faster.

**Good**: PR that adds SDR valuation basket composition data
**Less good**: PR that adds SDR baskets, fixes a WEO bug, updates docs, and refactors caching

### Follow Existing Patterns

Look at existing code for patterns:
- How are fetchers structured?
- How is caching implemented?
- How are errors handled?

Match the existing style for consistency.

### Write Tests

All new features should have tests. Bug fixes should include a test that would have caught the bug.

### Document Your Code

Include docstrings for all public functions:

```python
def fetch_data(version: Optional[Version] = None) -> pd.DataFrame:
    """Fetch World Economic Outlook data.

    Args:
        version: Optional tuple of (month, year) to fetch specific release.
                 Month must be "April" or "October".
                 If None, fetches the latest available version.

    Returns:
        DataFrame containing WEO data with all indicators and countries.

    Raises:
        NoDataError: If the requested version is not available.
        TypeError: If version format is invalid.

    Example:
        >>> from imf_reader import weo
        >>> df = weo.fetch_data()
        >>> df.shape
        (531216, 14)
    """
```

### Be Respectful

We're all here to make imf-reader better. Be kind, constructive, and welcoming to other contributors.

## Project Structure

Understanding the codebase structure helps you contribute effectively:

```
imf-reader/
├── src/imf_reader/          # Main package source
│   ├── __init__.py          # Package initialization
│   ├── config.py            # Configuration and exceptions
│   ├── utils.py             # Utility functions
│   ├── weo/                 # WEO module
│   │   ├── __init__.py      # WEO exports
│   │   ├── reader.py        # Main fetch_data function
│   │   ├── scraper.py       # Web scraping logic
│   │   └── parser.py        # Data parsing logic
│   └── sdr/                 # SDR module
│       ├── __init__.py      # SDR exports
│       ├── read_announcements.py    # Allocations/holdings
│       ├── read_interest_rate.py    # Interest rates
│       ├── read_exchange_rate.py    # Exchange rates
│       └── clear_cache.py   # Cache management
├── tests/                   # Test suite
│   ├── test_weo.py
│   └── test_sdr.py
├── docs/                    # Documentation (MkDocs)
│   ├── index.md
│   ├── getting-started.md
│   └── ...
├── mkdocs.yml               # MkDocs configuration
├── pyproject.toml           # Project metadata and dependencies
└── README.md                # Project overview
```

## Questions?

If you have questions about contributing:

1. Check existing [GitHub Issues](https://github.com/ONEcampaign/imf-reader/issues)
2. Open a new issue with your question
3. Tag it with `question` label

## Thank You!

Your contributions help make imf-reader better for everyone. Whether it's code, documentation, bug reports, or feature ideas—thank you for being part of the project!

## License

By contributing to imf-reader, you agree that your contributions will be licensed under the MIT License.
