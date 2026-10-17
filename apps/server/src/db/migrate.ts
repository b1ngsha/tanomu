import { createDb, runMigrations } from "./client.ts";

const url = process.env.DATABASE_URL;
if (!url) throw new Error("DATABASE_URL is not set");
const db = createDb(url);
await runMigrations(db);
await db.$client.end();
console.log("migrations applied");
