Quick Fix for Windows:
Run these commands in order:

Install tsx globally:

npm install -g tsx
Install cross-env locally:

npm install cross-env
Run with cross-env:

npx cross-env NODE_ENV=development tsx server/index.ts
Alternative: Simple Windows Method
If the above doesn't work, try this simpler approach:

npx tsx server/index.ts
The app will work fine without the NODE_ENV variable - it just sets the environment to development mode.

Or: Edit package.json manually
Open your package.json file and change this line:

"dev": "NODE_ENV=development tsx server/index.ts",
To this:

"dev": "cross-env NODE_ENV=development tsx server/index.ts",
Then run:

npm run dev
Expected Result:
Once working, you should see:

No existing scenarios file found, starting fresh
[time] [express] serving on port 5000
Then open: http://localhost:5000

Try the first option (install tsx globally and use cross-env) - that should work right away!
