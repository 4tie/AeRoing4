# AI Coding Guide for Vibe Next (Pure Template)

This document provides instructions for AI agents on how to contribute to this project. Follow these principles strictly to ensure consistency and maintainability.

## Core Principles

1.  **Predictability**: Use established patterns only. Do not invent new ways of doing things.
2.  **Composability**: Build modular components. Keep logic in services, not in UI components.
3.  **No "Any"**: Always use strong typing. Generate types from DB schema or API responses.

## Directory Structure

- `/db`: Database schema (`schema.ts`) and client (`index.ts`). **Start here for new features.**
- `/lib/services`: Server-side business logic. API routes should call these.
- `/lib`: Core utilities (`request.ts`, `env.ts`, `errors.ts`, `logger.ts`).
- `/app/api`: Next.js Route Handlers. Use `handleApiError`.
- `/types`: Shared TypeScript definitions.

## Coding Standards

### 1. Database
- Define tables in `db/schema.ts`.
- Use `db` export from `@/db` for queries.

### 2. API Routes
- Return a standardized structure (or just the data if success).
- Use `handleApiError(error)` in `catch` blocks.
- Prefer `NextResponse.json()`.

### 3. Data Fetching
- **Server Components**: Call database services directly.
- **Client Components**: Use `apiClient` from `@/lib/request`.

### 4. UI & Feedback
- Use `sonner` for toast notifications.
- Use `shadcn/ui` patterns for components.
- Use `react-hook-form` + `zod` for all forms.

## Providing Feedback
Always inform the user when an action succeeds or fails using `toast()`.
