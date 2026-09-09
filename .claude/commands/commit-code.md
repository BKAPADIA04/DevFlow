Commit the current code changes to git.

Commit message:
$ARGUMENTS

Steps:

1. Check `git status` and inspect the diff.
2. If `$ARGUMENTS` is provided, use it as the commit message **exactly as given**.
3. If `$ARGUMENTS` is empty:

   * Analyze the current `git diff` and changed files.
   * Generate a concise, conventional commit message that accurately describes the changes.
   * Use the generated message for the commit.
4. Stage all changes with `git add .`.
5. Commit using the determined commit message.
6. Do not push.
7. Show the resulting commit hash and the commit message used.

Do not modify source files.
