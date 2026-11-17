export type Status = "in_stock" | "out_of_stock" | "not_listed" | "error";

export interface SourceProduct {
  platform: string;
  title: string;
  url: string;
  brand: string | null;
  category: "smartphone" | "tv" | "sneakers" | "apparel";
  colour: string | null;
  ram_gb: number | null;
  storage_gb: number | null;
  screen_in: number | null;
  model_number: string | null;
  gender: string | null;
  available: boolean | null;
  price: number | null;
  image: string | null;
}

export interface PlatformResult {
  platform: string;
  status: Status;
  url: string | null;
  title: string | null;
  price: number | null;
  image: string | null;
  confidence: number | null;
  reasons: string[];
  query: string | null;
  candidates_checked: number;
  error: string | null;
  note: string | null;
}

export interface CompareResponse {
  source: SourceProduct;
  results: PlatformResult[];
  elapsed_ms: number;
  cached: boolean;
}
