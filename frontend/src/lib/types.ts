export type ApplicationStatus =
  | "IN_PROGRESS"
  | "APPLIED"
  | "INTERVIEW"
  | "OFFER"
  | "REJECTED";

export interface Application {
  id: string;
  user_id: string;
  company_id: string;
  role: string;
  status: ApplicationStatus;
  source_url: string | null;
  date_applied: string | null;
  notes: string | null;
  created_at: string;
}

export interface Company {
  id: string;
  user_id: string;
  name: string;
  normalized_name: string;
  location: string | null;
  link: string | null;
  created_at: string;
}

export interface StructuredJD {
  summary: string;
  responsibilities: string[];
  required_qualifications: string[];
  preferred_qualifications: string[];
  tech_stack: string[];
  compensation: string | null;
  application_deadline: string | null;
  location: string | null;
  work_model: string | null;
  company_overview: string | null;
}

export interface JobDescription {
  id: string;
  application_id: string;
  raw_text: string;
  captured_at: string;
  structured_jd: StructuredJD | null;
}

export interface RawEmail {
  id: string;
  subject: string | null;
  sender: string | null;
  received_at: string | null;
  gemini_signal: string | null;
  gemini_confidence: number | null;
  body_snippet: string | null;
}

export interface EmailAccount {
  id: string;
  user_id: string;
  email: string;
  created_at: string;
}
