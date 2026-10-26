CREATE TYPE "public"."provider_protocol" AS ENUM('openai', 'anthropic', 'google');--> statement-breakpoint
CREATE TABLE "capability_bindings" (
	"capability" text PRIMARY KEY NOT NULL,
	"provider_id" uuid NOT NULL,
	"model" text NOT NULL,
	"vision" boolean DEFAULT false NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "providers" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"protocol" "provider_protocol" NOT NULL,
	"base_url" text NOT NULL,
	"api_key" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "capability_bindings" ADD CONSTRAINT "capability_bindings_provider_id_providers_id_fk" FOREIGN KEY ("provider_id") REFERENCES "public"."providers"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "providers_name_lower_idx" ON "providers" USING btree (lower("name"));