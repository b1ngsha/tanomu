import { drizzle } from "drizzle-orm/postgres-js";
import { migrate } from "drizzle-orm/postgres-js/migrator";
import postgres from "postgres";
import * as schema from "./schema.ts";

export type Db = ReturnType<typeof createDb>;

export function createDb(url: string) {
  return drizzle(postgres(url, { onnotice: () => {} }), { schema, casing: "snake_case" });
}

export async function runMigrations(db: Db): Promise<void> {
  await migrate(db, { migrationsFolder: new URL("../../drizzle", import.meta.url).pathname });
}
