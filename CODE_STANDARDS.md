# Code Standards

## File Size Limits

### Line Count Rules

- **Target**: Every file should be under 500-700 lines
- **Hard limit**: No file should exceed 800 lines
- **Temporary exception**: 1000 lines only if the file is legacy and hasn't been refactored yet

### Rationale

Smaller files are easier to:

- Read and understand
- Test and debug
- Maintain and refactor
- Review in pull requests

### Enforcement

- Automated line limit checker script: `scripts/check_line_limits.py`
- Pre-commit hook to enforce limits on new files
- CI pipeline check for all files



### Refactoring Strategy

When refactoring large files:

1. Identify logical sections/modules within the file
2. Extract related functions/classes into separate modules
3. Use composition over inheritance where appropriate
4. Maintain clear import/export structure
5. Update tests accordingly
6. Document the refactoring in commit messages
