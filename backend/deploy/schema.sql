--
-- PostgreSQL database dump
--

\restrict U5BTBxJcadSDHMbsbmb9fFaKRD99Et2nYh55P0dSATvyLcC8apv5Fj8Wv1cBCoQ

-- Dumped from database version 18.1
-- Dumped by pg_dump version 18.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ai_review; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_review (
    id bigint NOT NULL,
    assessment_id bigint NOT NULL,
    competence_id bigint,
    ai_review text NOT NULL,
    model_version character varying(50),
    confidence_score double precision,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_review_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_review_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_review_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_review_id_seq OWNED BY public.ai_review.id;


--
-- Name: ai_scenario_approval_token; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_scenario_approval_token (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    event_id bigint,
    event_sequence bigint NOT NULL,
    token character varying(128) NOT NULL,
    scope character varying(160) NOT NULL,
    scope_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(30) DEFAULT 'active'::character varying NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    consumed_by_user_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_scenario_approval_token_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_scenario_approval_token_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_scenario_approval_token_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_scenario_approval_token_id_seq OWNED BY public.ai_scenario_approval_token.id;


--
-- Name: ai_scenario_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_scenario_event (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    sequence bigint NOT NULL,
    event_name character varying(120) NOT NULL,
    status character varying(30) NOT NULL,
    provenance character varying(50),
    confidence double precision,
    payload_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_scenario_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_scenario_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_scenario_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_scenario_event_id_seq OWNED BY public.ai_scenario_event.id;


--
-- Name: ai_scenario_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_scenario_job (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    scenario_id bigint,
    status character varying(20) DEFAULT 'QUEUED'::character varying NOT NULL,
    prompt text NOT NULL,
    input_json jsonb NOT NULL,
    output_json jsonb,
    output_text text,
    error text,
    model character varying(100),
    celery_task_id character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone
);


--
-- Name: ai_scenario_job_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_scenario_job_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_scenario_job_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_scenario_job_id_seq OWNED BY public.ai_scenario_job.id;


--
-- Name: ai_scenario_job_step; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_scenario_job_step (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    sequence bigint NOT NULL,
    step_key character varying(200) NOT NULL,
    step_type character varying(50) NOT NULL,
    agent_name character varying(80),
    prompt_version character varying(80),
    input_hash character varying(64),
    input_json jsonb,
    output_json jsonb,
    status character varying(30) NOT NULL,
    attempts integer,
    model character varying(100),
    response_id character varying(255),
    usage_json jsonb,
    error_type character varying(100),
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone
);


--
-- Name: ai_scenario_job_step_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_scenario_job_step_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_scenario_job_step_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_scenario_job_step_id_seq OWNED BY public.ai_scenario_job_step.id;


--
-- Name: aircraft_airline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aircraft_airline (
    id bigint NOT NULL,
    airline_id bigint NOT NULL,
    code character varying(100) NOT NULL,
    name character varying(255),
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    color_hex character varying(7) DEFAULT '#284692'::character varying NOT NULL,
    CONSTRAINT ck_aircraft_airline_color_hex CHECK (((color_hex)::text ~ '^#[0-9A-Fa-f]{6}$'::text))
);


--
-- Name: aircraft_airline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aircraft_airline_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aircraft_airline_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aircraft_airline_id_seq OWNED BY public.aircraft_airline.id;


--
-- Name: airline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.airline (
    id bigint NOT NULL,
    code character varying(10),
    name character varying(255) NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    users_stored_in_local_db boolean DEFAULT true NOT NULL
);


--
-- Name: airline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.airline_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: airline_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.airline_id_seq OWNED BY public.airline.id;


--
-- Name: airline_position; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.airline_position (
    id bigint NOT NULL,
    airline_id bigint,
    name character varying(100) NOT NULL,
    normalized_name character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_airline_position_name_not_empty CHECK ((btrim((name)::text) <> ''::text))
);


--
-- Name: airline_position_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.airline_position_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: airline_position_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.airline_position_id_seq OWNED BY public.airline_position.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: auth_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_sessions (
    id uuid NOT NULL,
    user_id bigint NOT NULL,
    refresh_jti uuid NOT NULL,
    refresh_expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoked_reason character varying(100),
    ip_address character varying(45),
    user_agent character varying(512),
    device_id character varying(255),
    device_name character varying(255),
    platform character varying(64),
    app_version character varying(64)
);


--
-- Name: behavioural_indicator; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.behavioural_indicator (
    id bigint NOT NULL,
    code character varying(50) NOT NULL,
    short_name character varying(255),
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    competence_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    retired_at timestamp with time zone
);


--
-- Name: behavioural_indicator_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.behavioural_indicator_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: behavioural_indicator_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.behavioural_indicator_id_seq OWNED BY public.behavioural_indicator.id;


--
-- Name: block_folder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.block_folder (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    color_hex character varying(7),
    parent_id bigint,
    order_index integer DEFAULT 0 NOT NULL,
    airline_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    aircraft_id bigint NOT NULL,
    library_kind character varying(32) DEFAULT 'exercise'::character varying NOT NULL,
    archived_by bigint,
    archived_at timestamp with time zone,
    CONSTRAINT ck_block_folder_library_kind CHECK (((library_kind)::text = ANY ((ARRAY['exercise'::character varying, 'competence'::character varying])::text[])))
);


--
-- Name: block_folder_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.block_folder_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: block_folder_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.block_folder_id_seq OWNED BY public.block_folder.id;


--
-- Name: block_folder_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.block_folder_item (
    id bigint NOT NULL,
    folder_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    block_id bigint NOT NULL
);


--
-- Name: block_folder_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.block_folder_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: block_folder_item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.block_folder_item_id_seq OWNED BY public.block_folder_item.id;


--
-- Name: competence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.competence (
    id bigint NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    airline_id bigint CONSTRAINT competence_airline_id_not_null1 NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    retired_at timestamp with time zone,
    CONSTRAINT ck_competence_code_not_empty CHECK (((code)::text <> ''::text))
);


--
-- Name: competence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.competence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: competence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.competence_id_seq OWNED BY public.competence.id;


--
-- Name: crew_member_assessment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.crew_member_assessment (
    id bigint NOT NULL,
    training_session_id bigint NOT NULL,
    user_id bigint,
    training_role character varying(10) NOT NULL,
    summary text,
    result boolean,
    signature text,
    signed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    signature_storage_path character varying(2048),
    signature_storage_key character varying(128),
    signature_content_type character varying(255),
    signature_size_bytes bigint,
    signature_sha256 character varying(64),
    CONSTRAINT ck_crew_member_assessment_role CHECK (((training_role)::text = ANY ((ARRAY['cm1'::character varying, 'cm2'::character varying])::text[])))
);


--
-- Name: crew_member_assessment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.crew_member_assessment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crew_member_assessment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.crew_member_assessment_id_seq OWNED BY public.crew_member_assessment.id;


--
-- Name: element; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element (
    id bigint NOT NULL,
    default_duration_minutes integer,
    name character varying(255) NOT NULL,
    severity integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    airline_id bigint NOT NULL,
    aircraft_id bigint NOT NULL,
    archived_by bigint,
    archived_at timestamp with time zone,
    CONSTRAINT ck_element_severity_range CHECK (((severity >= 0) AND (severity <= 10)))
);


--
-- Name: element_block; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_block (
    id bigint NOT NULL,
    element_block_param_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    airline_id bigint NOT NULL,
    archived_by bigint,
    archived_at timestamp with time zone
);


--
-- Name: element_block_competence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_block_competence (
    id bigint NOT NULL,
    competence_id bigint NOT NULL,
    block_id bigint NOT NULL
);


--
-- Name: element_block_competence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_block_competence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_block_competence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_block_competence_id_seq OWNED BY public.element_block_competence.id;


--
-- Name: element_block_element; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_block_element (
    id bigint NOT NULL,
    block_id bigint NOT NULL,
    element_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    details text,
    starting_height integer,
    ending_height integer,
    profile_type character varying(20) DEFAULT 'FLAT'::character varying NOT NULL,
    CONSTRAINT ck_element_block_element_profile_type CHECK (((profile_type)::text = ANY ((ARRAY['FLAT'::character varying, 'UP'::character varying, 'DOWN'::character varying, 'LINKED'::character varying])::text[])))
);


--
-- Name: element_block_element_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_block_element_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_block_element_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_block_element_id_seq OWNED BY public.element_block_element.id;


--
-- Name: element_block_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_block_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_block_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_block_id_seq OWNED BY public.element_block.id;


--
-- Name: element_block_param; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_block_param (
    id bigint NOT NULL,
    duration_minutes integer,
    crew_member_number integer,
    original_tl_id bigint,
    destination_tl_id bigint,
    intensity character varying(50),
    zfw_t character varying(50),
    guidance_doc jsonb,
    guidance_plain_text text,
    CONSTRAINT ck_element_block_param_guidance_doc_object CHECK (((guidance_doc IS NULL) OR (jsonb_typeof(guidance_doc) = 'object'::text)))
);


--
-- Name: element_block_param_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_block_param_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_block_param_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_block_param_id_seq OWNED BY public.element_block_param.id;


--
-- Name: element_folder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_folder (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    color_hex character varying(7),
    parent_id bigint,
    order_index integer DEFAULT 0 NOT NULL,
    airline_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    aircraft_id bigint NOT NULL,
    archived_by bigint,
    archived_at timestamp with time zone
);


--
-- Name: element_folder_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_folder_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_folder_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_folder_id_seq OWNED BY public.element_folder.id;


--
-- Name: element_folder_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_folder_item (
    id bigint NOT NULL,
    folder_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    element_id bigint NOT NULL
);


--
-- Name: element_folder_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_folder_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_folder_item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_folder_item_id_seq OWNED BY public.element_folder_item.id;


--
-- Name: element_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_id_seq OWNED BY public.element.id;


--
-- Name: exercise; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exercise (
    id bigint NOT NULL,
    client_uid character varying(36) NOT NULL,
    module_id bigint NOT NULL,
    exercise_param_id bigint,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    kind character varying(30) NOT NULL,
    duration_minutes integer,
    crew_member_number integer,
    CONSTRAINT ck_exercise_crew_member_number CHECK (((crew_member_number IS NULL) OR (crew_member_number = ANY (ARRAY[1, 2])))),
    CONSTRAINT ck_exercise_duration_minutes_non_negative CHECK (((duration_minutes IS NULL) OR (duration_minutes >= 0))),
    CONSTRAINT ck_exercise_kind CHECK (((kind)::text = ANY ((ARRAY['standard'::character varying, 'preparation'::character varying, 'coffee_break'::character varying, 'individual'::character varying])::text[]))),
    CONSTRAINT ck_exercise_order_index_non_negative CHECK ((order_index >= 0))
);


--
-- Name: exercise_competence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exercise_competence (
    id bigint NOT NULL,
    competence_id bigint NOT NULL,
    exercise_id bigint NOT NULL
);


--
-- Name: exercise_competence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exercise_competence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exercise_competence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exercise_competence_id_seq OWNED BY public.exercise_competence.id;


--
-- Name: exercise_element; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exercise_element (
    id bigint NOT NULL,
    exercise_id bigint NOT NULL,
    element_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    details text,
    starting_height integer,
    ending_height integer,
    profile_type character varying(20) DEFAULT 'FLAT'::character varying NOT NULL,
    CONSTRAINT ck_exercise_element_profile_type CHECK (((profile_type)::text = ANY ((ARRAY['FLAT'::character varying, 'UP'::character varying, 'DOWN'::character varying, 'LINKED'::character varying])::text[])))
);


--
-- Name: exercise_element_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exercise_element_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exercise_element_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exercise_element_id_seq OWNED BY public.exercise_element.id;


--
-- Name: exercise_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exercise_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exercise_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exercise_id_seq OWNED BY public.exercise.id;


--
-- Name: exercise_image; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exercise_image (
    id bigint NOT NULL,
    exercise_id bigint NOT NULL,
    storage_key character varying(128) NOT NULL,
    storage_path character varying(2048) NOT NULL,
    original_filename character varying(512) NOT NULL,
    content_type character varying(255) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    display_name character varying(255),
    CONSTRAINT ck_exercise_image_order_index_non_negative CHECK ((order_index >= 0))
);


--
-- Name: exercise_image_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exercise_image_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exercise_image_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exercise_image_id_seq OWNED BY public.exercise_image.id;


--
-- Name: exercise_param; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exercise_param (
    id bigint NOT NULL,
    original_tl_id bigint,
    destination_tl_id bigint,
    intensity character varying(50),
    zfw_t character varying(50),
    guidance_doc jsonb,
    guidance_plain_text text,
    CONSTRAINT ck_exercise_param_guidance_doc_object CHECK (((guidance_doc IS NULL) OR (jsonb_typeof(guidance_doc) = 'object'::text)))
);


--
-- Name: exercise_param_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exercise_param_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exercise_param_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exercise_param_id_seq OWNED BY public.exercise_param.id;


--
-- Name: feedback_attachment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_attachment (
    id bigint NOT NULL,
    ticket_id bigint NOT NULL,
    original_filename character varying(512) NOT NULL,
    content_type character varying(255),
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    storage_path character varying(2048) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: feedback_attachment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.feedback_attachment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: feedback_attachment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.feedback_attachment_id_seq OWNED BY public.feedback_attachment.id;


--
-- Name: feedback_ticket; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_ticket (
    id bigint NOT NULL,
    user_id bigint,
    subject character varying(255) NOT NULL,
    message text NOT NULL,
    page_url character varying(2048),
    client_info jsonb,
    status character varying(50) DEFAULT 'OPEN'::character varying NOT NULL,
    admin_reply text,
    admin_user_id bigint,
    admin_replied_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: feedback_ticket_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.feedback_ticket_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: feedback_ticket_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.feedback_ticket_id_seq OWNED BY public.feedback_ticket.id;


--
-- Name: final_report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.final_report (
    id bigint NOT NULL,
    assessment_id bigint NOT NULL,
    competence_id bigint NOT NULL,
    grade character varying(20) NOT NULL,
    comments text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    grading_scale_value_id bigint,
    grade_code_snapshot character varying(50) NOT NULL,
    grade_label_snapshot character varying(100) NOT NULL,
    grade_score_snapshot numeric(10,4) NOT NULL,
    grade_color_hex_snapshot character varying(7),
    grade_weight_snapshot numeric(10,4) NOT NULL,
    competence_code_snapshot character varying(50),
    competence_name_snapshot character varying(255),
    competence_order_index_snapshot integer
);


--
-- Name: final_report_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.final_report_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: final_report_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.final_report_id_seq OWNED BY public.final_report.id;


--
-- Name: flight_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.flight_type (
    id bigint NOT NULL,
    airline_id bigint NOT NULL,
    name character varying(100) NOT NULL,
    normalized_name character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_main boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_flight_type_name_not_empty CHECK ((btrim((name)::text) <> ''::text))
);


--
-- Name: flight_type_competence_threshold; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.flight_type_competence_threshold (
    id bigint NOT NULL,
    competence_id bigint NOT NULL,
    flight_type_id bigint NOT NULL,
    value numeric(10,4) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_flight_type_competence_threshold_value_non_negative CHECK ((value >= (0)::numeric))
);


--
-- Name: flight_type_competence_threshold_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.flight_type_competence_threshold_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flight_type_competence_threshold_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.flight_type_competence_threshold_id_seq OWNED BY public.flight_type_competence_threshold.id;


--
-- Name: flight_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.flight_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flight_type_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.flight_type_id_seq OWNED BY public.flight_type.id;


--
-- Name: grading_scale_value; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grading_scale_value (
    id bigint NOT NULL,
    grading_scheme_id bigint NOT NULL,
    code character varying(50) NOT NULL,
    label character varying(100) NOT NULL,
    score_numeric numeric(10,4) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    color_hex character varying(7),
    is_pass boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    grade_weight numeric(10,4) DEFAULT 1.0000 NOT NULL,
    CONSTRAINT ck_grading_scale_value_code_not_empty CHECK (((code)::text <> ''::text)),
    CONSTRAINT ck_grading_scale_value_color_hex CHECK (((color_hex IS NULL) OR ((color_hex)::text ~ '^#[0-9A-Fa-f]{6}$'::text))),
    CONSTRAINT ck_grading_scale_value_grade_weight_positive CHECK ((grade_weight > (0)::numeric)),
    CONSTRAINT ck_grading_scale_value_label_not_empty CHECK (((label)::text <> ''::text))
);


--
-- Name: grading_scale_value_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grading_scale_value_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grading_scale_value_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grading_scale_value_id_seq OWNED BY public.grading_scale_value.id;


--
-- Name: grading_scheme; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grading_scheme (
    id bigint NOT NULL,
    airline_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_grading_scheme_name_not_empty CHECK (((name)::text <> ''::text))
);


--
-- Name: grading_scheme_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grading_scheme_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grading_scheme_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grading_scheme_id_seq OWNED BY public.grading_scheme.id;


--
-- Name: mistake_report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mistake_report (
    id bigint NOT NULL,
    assessment_id bigint NOT NULL,
    competence_id bigint,
    behavioural_indicator_id bigint,
    is_positive boolean DEFAULT false NOT NULL,
    comment text,
    hashtag character varying(100),
    "timestamp" timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    exercise_id bigint NOT NULL,
    exercise_offset_sec integer NOT NULL,
    exercise_session_key character varying(128) NOT NULL,
    training_session_exercise_id bigint NOT NULL,
    client_report_id uuid,
    timeline_source character varying(20) DEFAULT 'LEGACY_STATIC'::character varying NOT NULL,
    exercise_offset_ms bigint,
    assignment_event_id_at_observation bigint,
    competence_code_snapshot character varying(50),
    competence_name_snapshot character varying(255),
    behavioural_indicator_code_snapshot character varying(50),
    behavioural_indicator_name_snapshot character varying(255),
    CONSTRAINT ck_mistake_report_exercise_offset_ms CHECK (((exercise_offset_ms IS NULL) OR (exercise_offset_ms >= 0))),
    CONSTRAINT ck_mistake_report_timeline_fields CHECK ((((timeline_source)::text = 'LEGACY_STATIC'::text) OR ((client_report_id IS NOT NULL) AND (exercise_offset_ms IS NOT NULL) AND (assignment_event_id_at_observation IS NOT NULL)))),
    CONSTRAINT ck_mistake_report_timeline_source CHECK (((timeline_source)::text = ANY ((ARRAY['TIMELINE'::character varying, 'LEGACY_STATIC'::character varying])::text[])))
);


--
-- Name: mistake_report_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.mistake_report_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mistake_report_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.mistake_report_id_seq OWNED BY public.mistake_report.id;


--
-- Name: module; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.module (
    id bigint NOT NULL,
    client_uid character varying(36) NOT NULL,
    scenario_id bigint NOT NULL,
    content_subcolumn_id bigint,
    order_index integer DEFAULT 0 NOT NULL,
    duration_minutes integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: module_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.module_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: module_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.module_id_seq OWNED BY public.module.id;


--
-- Name: privileges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.privileges (
    id bigint NOT NULL,
    public_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    description character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: privileges_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.privileges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: privileges_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.privileges_id_seq OWNED BY public.privileges.id;


--
-- Name: role_privileges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_privileges (
    role_id bigint NOT NULL,
    privilege_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id bigint NOT NULL,
    public_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    description character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: scenario; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario (
    id bigint NOT NULL,
    airline_id bigint NOT NULL,
    content_version bigint DEFAULT '1'::bigint NOT NULL,
    code character varying(50),
    title character varying(255) NOT NULL,
    comments text,
    status character varying(50) DEFAULT 'DRAFT'::character varying NOT NULL,
    published_at timestamp with time zone,
    valid_until timestamp with time zone,
    created_by bigint,
    updated_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    engines character varying(50),
    aircraft_id bigint NOT NULL,
    archived_by bigint,
    archived_at timestamp with time zone,
    deleted_by bigint,
    deleted_at timestamp with time zone
);


--
-- Name: scenario_content_cell; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_cell (
    id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    requirement_id bigint NOT NULL,
    set_label_id bigint NOT NULL,
    subcolumn_id bigint NOT NULL,
    value boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scenario_content_cell_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_cell_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_cell_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_cell_id_seq OWNED BY public.scenario_content_cell.id;


--
-- Name: scenario_content_folder; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_folder (
    id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    parent_id bigint,
    name character varying(255) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scenario_content_folder_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_folder_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_folder_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_folder_id_seq OWNED BY public.scenario_content_folder.id;


--
-- Name: scenario_content_requirement; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_requirement (
    id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    folder_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    topic_name character varying(255) NOT NULL
);


--
-- Name: scenario_content_requirement_element; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_requirement_element (
    id bigint CONSTRAINT scenario_content_requirement_element_id_not_null1 NOT NULL,
    requirement_id bigint NOT NULL,
    element_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scenario_content_requirement_element_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_requirement_element_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_requirement_element_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_requirement_element_id_seq OWNED BY public.scenario_content_requirement_element.id;


--
-- Name: scenario_content_requirement_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_requirement_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_requirement_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_requirement_id_seq OWNED BY public.scenario_content_requirement.id;


--
-- Name: scenario_content_set; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_set (
    id bigint NOT NULL,
    airline_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    valid_from timestamp with time zone,
    valid_to timestamp with time zone,
    created_by bigint,
    updated_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    aircraft_id bigint NOT NULL
);


--
-- Name: scenario_content_set_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_set_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_set_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_set_id_seq OWNED BY public.scenario_content_set.id;


--
-- Name: scenario_content_set_label; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_set_label (
    id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    label character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scenario_content_set_label_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_set_label_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_set_label_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_set_label_id_seq OWNED BY public.scenario_content_set_label.id;


--
-- Name: scenario_content_set_label_scenario; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_set_label_scenario (
    id bigint NOT NULL,
    label_id bigint NOT NULL,
    scenario_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scenario_content_set_label_scenario_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_set_label_scenario_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_set_label_scenario_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_set_label_scenario_id_seq OWNED BY public.scenario_content_set_label_scenario.id;


--
-- Name: scenario_content_subcolumn; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_content_subcolumn (
    id bigint NOT NULL,
    content_set_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scenario_content_subcolumn_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_content_subcolumn_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_content_subcolumn_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_content_subcolumn_id_seq OWNED BY public.scenario_content_subcolumn.id;


--
-- Name: scenario_day_module; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_day_module (
    id bigint NOT NULL,
    scenario_id bigint NOT NULL,
    module_id bigint NOT NULL,
    day_index integer DEFAULT 1 NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_scenario_day_module_day_index_positive CHECK ((day_index >= 1)),
    CONSTRAINT ck_scenario_day_module_order_index_non_negative CHECK ((order_index >= 0))
);


--
-- Name: scenario_day_module_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_day_module_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_day_module_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_day_module_id_seq OWNED BY public.scenario_day_module.id;


--
-- Name: scenario_edit_lock; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_edit_lock (
    id bigint NOT NULL,
    scenario_id bigint NOT NULL,
    user_id bigint,
    client_session_id character varying(80) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scenario_edit_lock_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_edit_lock_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_edit_lock_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_edit_lock_id_seq OWNED BY public.scenario_edit_lock.id;


--
-- Name: scenario_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_id_seq OWNED BY public.scenario.id;


--
-- Name: scenario_pdf; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_pdf (
    id bigint NOT NULL,
    scenario_id bigint NOT NULL,
    storage_key character varying(128) NOT NULL,
    storage_path character varying(2048) NOT NULL,
    original_filename character varying(512) NOT NULL,
    display_name character varying(255),
    content_type character varying(255) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_scenario_pdf_order_index_non_negative CHECK ((order_index >= 0))
);


--
-- Name: scenario_pdf_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_pdf_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_pdf_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_pdf_id_seq OWNED BY public.scenario_pdf.id;


--
-- Name: scenario_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_revision (
    id bigint NOT NULL,
    scenario_id bigint NOT NULL,
    created_by bigint,
    kind character varying(20) DEFAULT 'AUTO'::character varying NOT NULL,
    label character varying(255),
    signature character varying(64) NOT NULL,
    client_entry_id character varying(80),
    client_created_at_ms bigint,
    snapshot_json jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revision_number integer NOT NULL,
    action character varying(20),
    branch_id character varying(80),
    parent_client_entry_id character varying(80),
    parent_revision_id bigint,
    base_client_entry_id character varying(80),
    restored_from_client_entry_id character varying(80)
);


--
-- Name: scenario_revision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_revision_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_revision_id_seq OWNED BY public.scenario_revision.id;


--
-- Name: speech_artifact; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_artifact (
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    type character varying(64) NOT NULL,
    path character varying(2048) NOT NULL,
    sha256 character varying(64) NOT NULL,
    size_bytes bigint NOT NULL,
    content_type character varying(255) NOT NULL,
    status character varying(20) DEFAULT 'ready'::character varying NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_speech_artifact_status CHECK (((status)::text = ANY ((ARRAY['uploading'::character varying, 'ready'::character varying, 'error'::character varying])::text[])))
);


--
-- Name: speech_diarization_block; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_diarization_block (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    block_index integer NOT NULL,
    chunk_from integer NOT NULL,
    chunk_to integer NOT NULL,
    start_ms bigint NOT NULL,
    end_ms bigint NOT NULL,
    block_wav_artifact_id uuid,
    diarization_artifact_id uuid,
    speaker_map jsonb,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_speech_diarization_block_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'started'::character varying, 'diarized'::character varying, 'stitched'::character varying, 'error'::character varying, 'waiting_for_gpu'::character varying])::text[])))
);


--
-- Name: speech_diarization_block_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.speech_diarization_block_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: speech_diarization_block_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.speech_diarization_block_id_seq OWNED BY public.speech_diarization_block.id;


--
-- Name: speech_external_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_external_job (
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    chunk_index integer,
    block_index integer,
    job_type character varying(32) NOT NULL,
    provider character varying(32) NOT NULL,
    provider_job_id character varying(255) NOT NULL,
    request_payload jsonb,
    result_payload jsonb,
    status character varying(20) DEFAULT 'submitted'::character varying NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT ck_speech_external_job_provider CHECK (((provider)::text = 'aws_batch'::text)),
    CONSTRAINT ck_speech_external_job_status CHECK (((status)::text = ANY ((ARRAY['submitted'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_speech_external_job_type CHECK (((job_type)::text = ANY ((ARRAY['asr_chunk'::character varying, 'diarize_block'::character varying])::text[])))
);


--
-- Name: speech_review; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_review (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    review_json jsonb,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_speech_review_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying, 'done'::character varying, 'error'::character varying])::text[])))
);


--
-- Name: speech_review_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.speech_review_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: speech_review_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.speech_review_id_seq OWNED BY public.speech_review.id;


--
-- Name: speech_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_session (
    id uuid NOT NULL,
    user_id bigint NOT NULL,
    chunk_seconds integer DEFAULT 300 NOT NULL,
    status character varying(20) DEFAULT 'recording'::character varying NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    expected_chunks integer DEFAULT 0 NOT NULL,
    exec_mode character varying(20) DEFAULT 'only_cpu'::character varying NOT NULL,
    transcript_artifact_id uuid,
    training_session_id bigint,
    CONSTRAINT ck_speech_session_status CHECK (((status)::text = ANY ((ARRAY['recording'::character varying, 'finalizing'::character varying, 'done'::character varying, 'error'::character varying])::text[])))
);


--
-- Name: speech_session_chunk; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_session_chunk (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    start_offset_ms integer NOT NULL,
    s3_key_audio character varying(1024) NOT NULL,
    s3_key_transcript_json character varying(1024),
    sha256 character varying(64) NOT NULL,
    size_bytes bigint NOT NULL,
    content_type character varying(255) DEFAULT 'audio/wav'::character varying NOT NULL,
    upload_status character varying(20) DEFAULT 'uploading'::character varying NOT NULL,
    transcribe_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    transcribe_job_name character varying(255),
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    duration_ms integer DEFAULT 0 NOT NULL,
    raw_artifact_id uuid,
    wav_artifact_id uuid,
    asr_artifact_id uuid,
    CONSTRAINT ck_speech_session_chunk_transcribe_status CHECK (((transcribe_status)::text = ANY ((ARRAY['pending'::character varying, 'started'::character varying, 'transcript_ready'::character varying, 'processed'::character varying, 'error'::character varying, 'waiting_for_gpu'::character varying])::text[]))),
    CONSTRAINT ck_speech_session_chunk_upload_status CHECK (((upload_status)::text = ANY ((ARRAY['recorded'::character varying, 'uploading'::character varying, 'uploaded'::character varying])::text[])))
);


--
-- Name: speech_session_chunk_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.speech_session_chunk_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: speech_session_chunk_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.speech_session_chunk_id_seq OWNED BY public.speech_session_chunk.id;


--
-- Name: speech_speaker_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_speaker_profile (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    pilot character varying(1) NOT NULL,
    centroid_vector jsonb NOT NULL,
    samples_sec_total integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_speech_speaker_profile_pilot CHECK (((pilot)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying])::text[])))
);


--
-- Name: speech_speaker_profile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.speech_speaker_profile_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: speech_speaker_profile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.speech_speaker_profile_id_seq OWNED BY public.speech_speaker_profile.id;


--
-- Name: speech_transcript_segment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.speech_transcript_segment (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    start_ms_global bigint NOT NULL,
    end_ms_global bigint NOT NULL,
    pilot character varying(10) NOT NULL,
    text text NOT NULL,
    confidence double precision,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_speech_transcript_segment_pilot CHECK (((pilot)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'unknown'::character varying])::text[])))
);


--
-- Name: speech_transcript_segment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.speech_transcript_segment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: speech_transcript_segment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.speech_transcript_segment_id_seq OWNED BY public.speech_transcript_segment.id;


--
-- Name: take_off_landing_param; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.take_off_landing_param (
    id bigint NOT NULL,
    airport_name character varying(255),
    time_of_day character varying(50),
    runway character varying(20),
    braking_action character varying(50),
    special_wx character varying(255),
    wind_dir character varying(50),
    wind_speed character varying(50),
    wind_gust character varying(50),
    visibility_value character varying(50),
    clouds_amount character varying(50),
    clouds_ceiling_ft character varying(50),
    rvr_h character varying(50),
    rvr_v character varying(50),
    temperature_c character varying(50),
    qnh_hpa character varying(50),
    fuel character varying(50),
    cg_percent character varying(50)
);


--
-- Name: take_off_landing_param_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.take_off_landing_param_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: take_off_landing_param_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.take_off_landing_param_id_seq OWNED BY public.take_off_landing_param.id;


--
-- Name: takeoff_param_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.takeoff_param_details (
    take_off_landing_param_id bigint NOT NULL,
    thrust_setting character varying(100),
    flaps_setting character varying(50),
    v2_speed character varying(50),
    vr_speed character varying(50),
    v1_speed character varying(50),
    sid character varying(100),
    squawk_code character varying(10),
    frequency character varying(50),
    climb character varying(255)
);


--
-- Name: training_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session (
    id bigint NOT NULL,
    instructor_id bigint,
    scheduled_at timestamp with time zone,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    status character varying(50) DEFAULT 'SCHEDULED'::character varying NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    scenario_day_module_id bigint,
    grading_scheme_id bigint NOT NULL,
    submission_status character varying(50) DEFAULT 'DRAFT'::character varying NOT NULL,
    submitted_at timestamp with time zone,
    submission_error text,
    submit_idempotency_key character varying(128),
    scenario_id_snapshot bigint,
    scenario_title_snapshot character varying(255),
    scenario_label_snapshot character varying(255),
    scenario_revision_id bigint,
    scenario_revision_number integer,
    day_index_snapshot integer,
    days_count_snapshot integer,
    aircraft_id_snapshot bigint,
    aircraft_code_snapshot character varying(50),
    client_creation_id uuid,
    client_creation_payload_hash character varying(64),
    comment_contract_version integer DEFAULT 0 NOT NULL,
    evaluation_catalog_snapshot jsonb,
    evaluation_catalog_sha256 character varying(64),
    CONSTRAINT ck_training_session_comment_contract_version CHECK ((comment_contract_version = ANY (ARRAY[0, 1]))),
    CONSTRAINT ck_training_session_submission_status CHECK (((submission_status)::text = ANY ((ARRAY['DRAFT'::character varying, 'WAITING_ASSESSMENTS'::character varying, 'WAITING_SPEECH'::character varying, 'COMPLETED'::character varying, 'ERROR'::character varying])::text[])))
);


--
-- Name: training_session_crew_assignment_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_crew_assignment_event (
    id bigint NOT NULL,
    public_id uuid NOT NULL,
    client_event_id uuid,
    training_session_id bigint CONSTRAINT training_session_crew_assignment_e_training_session_id_not_null NOT NULL,
    server_revision bigint NOT NULL,
    event_kind character varying(20) NOT NULL,
    event_scope character varying(30) NOT NULL,
    writer_instance_id uuid,
    writer_epoch integer NOT NULL,
    client_sequence bigint NOT NULL,
    previous_event_public_id uuid,
    occurred_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by bigint,
    training_session_exercise_id bigint,
    exercise_session_key uuid,
    exercise_offset_ms bigint,
    timer_state character varying(20) NOT NULL,
    cm1_assessment_id_after bigint CONSTRAINT training_session_crew_assignme_cm1_assessment_id_after_not_null NOT NULL,
    cm2_assessment_id_after bigint CONSTRAINT training_session_crew_assignme_cm2_assessment_id_after_not_null NOT NULL,
    payload_hash character varying(64) NOT NULL,
    client_app_version character varying(50),
    client_platform character varying(30),
    CONSTRAINT ck_training_crew_event_context CHECK (((((event_scope)::text = 'SESSION'::text) AND (training_session_exercise_id IS NULL) AND (exercise_session_key IS NULL) AND (exercise_offset_ms IS NULL) AND ((timer_state)::text = 'NONE'::text)) OR (((event_scope)::text = 'EXERCISE_RUN'::text) AND (training_session_exercise_id IS NOT NULL) AND (exercise_session_key IS NOT NULL) AND (exercise_offset_ms IS NOT NULL) AND ((timer_state)::text = ANY ((ARRAY['RUNNING'::character varying, 'PAUSED'::character varying])::text[]))))),
    CONSTRAINT ck_training_crew_event_distinct_assessments CHECK ((cm1_assessment_id_after <> cm2_assessment_id_after)),
    CONSTRAINT ck_training_crew_event_kind CHECK (((event_kind)::text = ANY ((ARRAY['INITIAL'::character varying, 'SWAP'::character varying])::text[]))),
    CONSTRAINT ck_training_crew_event_kind_fields CHECK (((((event_kind)::text = 'INITIAL'::text) AND (server_revision = 0) AND (writer_epoch = 0) AND (client_sequence = 0) AND (writer_instance_id IS NULL) AND (client_event_id IS NULL) AND (previous_event_public_id IS NULL) AND ((event_scope)::text = 'SESSION'::text)) OR (((event_kind)::text = 'SWAP'::text) AND (server_revision >= 1) AND (writer_epoch >= 1) AND (client_sequence >= 1) AND (writer_instance_id IS NOT NULL) AND (client_event_id = public_id) AND (previous_event_public_id IS NOT NULL)))),
    CONSTRAINT ck_training_crew_event_offset CHECK (((exercise_offset_ms IS NULL) OR (exercise_offset_ms >= 0))),
    CONSTRAINT ck_training_crew_event_scope CHECK (((event_scope)::text = ANY ((ARRAY['SESSION'::character varying, 'EXERCISE_RUN'::character varying])::text[]))),
    CONSTRAINT ck_training_crew_event_timer_state CHECK (((timer_state)::text = ANY ((ARRAY['NONE'::character varying, 'RUNNING'::character varying, 'PAUSED'::character varying])::text[])))
);


--
-- Name: training_session_crew_assignment_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_crew_assignment_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_crew_assignment_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_crew_assignment_event_id_seq OWNED BY public.training_session_crew_assignment_event.id;


--
-- Name: training_session_crew_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_crew_state (
    training_session_id bigint NOT NULL,
    current_revision bigint DEFAULT 0 NOT NULL,
    current_event_public_id uuid NOT NULL,
    current_writer_sequence bigint DEFAULT 0 NOT NULL,
    current_cm1_assessment_id bigint NOT NULL,
    current_cm2_assessment_id bigint NOT NULL,
    writer_instance_id uuid NOT NULL,
    writer_epoch integer DEFAULT 1 NOT NULL,
    capability_version integer DEFAULT 0 NOT NULL,
    live_swap_entitled boolean DEFAULT false NOT NULL,
    sealed_at timestamp with time zone,
    sealed_submit_idempotency_key character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_training_crew_state_capability_version CHECK ((capability_version >= 0)),
    CONSTRAINT ck_training_crew_state_distinct_assessments CHECK ((current_cm1_assessment_id <> current_cm2_assessment_id)),
    CONSTRAINT ck_training_crew_state_entitlement_version CHECK (((NOT live_swap_entitled) OR (capability_version >= 1))),
    CONSTRAINT ck_training_crew_state_revision CHECK ((current_revision >= 0)),
    CONSTRAINT ck_training_crew_state_seal_fields CHECK ((((sealed_at IS NULL) AND (sealed_submit_idempotency_key IS NULL)) OR ((sealed_at IS NOT NULL) AND (sealed_submit_idempotency_key IS NOT NULL)))),
    CONSTRAINT ck_training_crew_state_writer_epoch CHECK ((writer_epoch >= 1)),
    CONSTRAINT ck_training_crew_state_writer_sequence CHECK ((current_writer_sequence >= 0))
);


--
-- Name: training_session_draft; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_draft (
    id bigint NOT NULL,
    training_session_id bigint NOT NULL,
    user_id bigint NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    submitted boolean DEFAULT false NOT NULL,
    submitted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    contract_version integer DEFAULT 0 NOT NULL,
    writer_instance_id uuid,
    client_revision bigint DEFAULT '0'::bigint NOT NULL,
    payload_sha256 character varying(64),
    CONSTRAINT ck_training_session_draft_contract_version CHECK ((contract_version = ANY (ARRAY[0, 3]))),
    CONSTRAINT ck_training_session_draft_revision_nonnegative CHECK ((client_revision >= 0))
);


--
-- Name: training_session_draft_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_draft_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_draft_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_draft_id_seq OWNED BY public.training_session_draft.id;


--
-- Name: training_session_exercise; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_exercise (
    id bigint NOT NULL,
    training_session_id bigint NOT NULL,
    training_session_module_id bigint NOT NULL,
    runtime_exercise_id bigint NOT NULL,
    source_exercise_id bigint,
    source_block_id bigint,
    client_uid character varying(36) NOT NULL,
    source_kind_snapshot character varying(30) NOT NULL,
    kind character varying(30) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    duration_minutes integer,
    crew_member_number integer,
    setup_label character varying(50),
    name character varying(255),
    display_label character varying(255),
    step_label character varying(255),
    is_service boolean DEFAULT false NOT NULL,
    aircraft_ac_type character varying(50),
    aircraft_engines character varying(255),
    departure_weather_original character varying(255),
    departure_weather_destination character varying(255),
    departure_weather_daytime character varying(255),
    departure_weather_special character varying(255),
    departure_weather_runway character varying(255),
    departure_weather_braking_action character varying(255),
    departure_weather_wind character varying(255),
    departure_weather_visibility character varying(255),
    departure_weather_clouds character varying(255),
    departure_weather_temp character varying(50),
    departure_weather_qnh character varying(50),
    departure_aircraft_zfw character varying(50),
    departure_aircraft_gw character varying(50),
    departure_aircraft_cg character varying(50),
    departure_aircraft_fuel character varying(50),
    departure_aircraft_flaps character varying(50),
    departure_aircraft_thrust character varying(50),
    departure_aircraft_v1 character varying(50),
    departure_aircraft_vr character varying(50),
    departure_aircraft_v2 character varying(50),
    departure_atc_sid character varying(255),
    departure_atc_climb character varying(255),
    departure_atc_frequency character varying(255),
    departure_atc_transponder character varying(255),
    arrival_weather_original character varying(255),
    arrival_weather_destination character varying(255),
    arrival_weather_daytime character varying(255),
    arrival_weather_special character varying(255),
    arrival_weather_runway character varying(255),
    arrival_weather_braking_action character varying(255),
    arrival_weather_wind character varying(255),
    arrival_weather_visibility character varying(255),
    arrival_weather_clouds character varying(255),
    arrival_weather_temp character varying(50),
    arrival_weather_qnh character varying(50),
    arrival_aircraft_zfw character varying(50),
    arrival_aircraft_gw character varying(50),
    arrival_aircraft_cg character varying(50),
    arrival_aircraft_fuel character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    guidance_doc jsonb,
    guidance_plain_text text,
    resolved_for_assessment_id bigint,
    CONSTRAINT ck_training_session_exercise_crew_member_number CHECK (((crew_member_number IS NULL) OR (crew_member_number = ANY (ARRAY[1, 2])))),
    CONSTRAINT ck_training_session_exercise_duration_minutes CHECK (((duration_minutes IS NULL) OR (duration_minutes >= 0))),
    CONSTRAINT ck_training_session_exercise_guidance_doc_object CHECK (((guidance_doc IS NULL) OR (jsonb_typeof(guidance_doc) = 'object'::text))),
    CONSTRAINT ck_training_session_exercise_kind CHECK (((kind)::text = ANY ((ARRAY['standard'::character varying, 'preparation'::character varying, 'coffee_break'::character varying, 'individual'::character varying])::text[]))),
    CONSTRAINT ck_training_session_exercise_order_index CHECK ((order_index >= 0)),
    CONSTRAINT ck_training_session_exercise_source_kind CHECK (((source_kind_snapshot)::text = ANY ((ARRAY['standard'::character varying, 'preparation'::character varying, 'coffee_break'::character varying, 'individual'::character varying])::text[])))
);


--
-- Name: training_session_exercise_competence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_exercise_competence (
    id bigint NOT NULL,
    training_session_exercise_id bigint CONSTRAINT training_session_exercise_c_training_session_exercise__not_null NOT NULL,
    source_competence_id bigint,
    code_snapshot character varying(50) NOT NULL,
    name_snapshot character varying(255) NOT NULL,
    order_index_snapshot integer DEFAULT 0 CONSTRAINT training_session_exercise_compete_order_index_snapshot_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_training_session_exercise_competence_order_index CHECK ((order_index_snapshot >= 0))
);


--
-- Name: training_session_exercise_competence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_exercise_competence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_exercise_competence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_exercise_competence_id_seq OWNED BY public.training_session_exercise_competence.id;


--
-- Name: training_session_exercise_crew_segment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_exercise_crew_segment (
    id bigint NOT NULL,
    training_session_id bigint CONSTRAINT training_session_exercise_crew_seg_training_session_id_not_null NOT NULL,
    exercise_session_key uuid CONSTRAINT training_session_exercise_crew_se_exercise_session_key_not_null NOT NULL,
    training_session_exercise_id bigint CONSTRAINT training_session_exercise__training_session_exercise__not_null1 NOT NULL,
    segment_index integer NOT NULL,
    from_offset_ms bigint NOT NULL,
    to_offset_ms bigint NOT NULL,
    cm1_assessment_id bigint CONSTRAINT training_session_exercise_crew_segme_cm1_assessment_id_not_null NOT NULL,
    cm2_assessment_id bigint CONSTRAINT training_session_exercise_crew_segme_cm2_assessment_id_not_null NOT NULL,
    pf_assessment_id bigint,
    pm_assessment_id bigint,
    starts_after_event_public_id uuid CONSTRAINT training_session_exercise_c_starts_after_event_public__not_null NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_training_crew_segment_distinct_assessments CHECK ((cm1_assessment_id <> cm2_assessment_id)),
    CONSTRAINT ck_training_crew_segment_index CHECK ((segment_index >= 0)),
    CONSTRAINT ck_training_crew_segment_interval CHECK (((from_offset_ms >= 0) AND (from_offset_ms < to_offset_ms))),
    CONSTRAINT ck_training_crew_segment_pf_pm_mapping CHECK ((((pf_assessment_id IS NULL) AND (pm_assessment_id IS NULL)) OR (((pf_assessment_id = cm1_assessment_id) AND (pm_assessment_id = cm2_assessment_id)) OR ((pf_assessment_id = cm2_assessment_id) AND (pm_assessment_id = cm1_assessment_id)))))
);


--
-- Name: training_session_exercise_crew_segment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_exercise_crew_segment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_exercise_crew_segment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_exercise_crew_segment_id_seq OWNED BY public.training_session_exercise_crew_segment.id;


--
-- Name: training_session_exercise_element; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_exercise_element (
    id bigint NOT NULL,
    training_session_exercise_id bigint CONSTRAINT training_session_exercise_e_training_session_exercise__not_null NOT NULL,
    source_exercise_element_id bigint,
    source_element_id bigint,
    content_id integer,
    order_index integer DEFAULT 0 NOT NULL,
    details text,
    starting_height integer,
    ending_height integer,
    profile_type character varying(20) DEFAULT 'FLAT'::character varying NOT NULL,
    type_label_snapshot character varying(50),
    color_hex_snapshot character varying(7),
    element_name_snapshot character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_training_session_exercise_element_order_index CHECK ((order_index >= 0)),
    CONSTRAINT ck_training_session_exercise_element_profile_type CHECK (((profile_type)::text = ANY ((ARRAY['FLAT'::character varying, 'UP'::character varying, 'DOWN'::character varying, 'LINKED'::character varying])::text[])))
);


--
-- Name: training_session_exercise_element_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_exercise_element_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_exercise_element_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_exercise_element_id_seq OWNED BY public.training_session_exercise_element.id;


--
-- Name: training_session_exercise_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_exercise_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_exercise_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_exercise_id_seq OWNED BY public.training_session_exercise.id;


--
-- Name: training_session_exercise_image; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_exercise_image (
    id bigint NOT NULL,
    training_session_exercise_id bigint CONSTRAINT training_session_exercise_i_training_session_exercise__not_null NOT NULL,
    source_exercise_image_id bigint,
    storage_key character varying(128) NOT NULL,
    storage_path character varying(2048) NOT NULL,
    original_filename character varying(512) NOT NULL,
    content_type character varying(255) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    display_name character varying(255),
    CONSTRAINT ck_training_session_exercise_image_order_index CHECK ((order_index >= 0))
);


--
-- Name: training_session_exercise_image_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_exercise_image_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_exercise_image_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_exercise_image_id_seq OWNED BY public.training_session_exercise_image.id;


--
-- Name: training_session_exercise_run; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_exercise_run (
    exercise_session_key uuid NOT NULL,
    training_session_id bigint NOT NULL,
    training_session_exercise_id bigint CONSTRAINT training_session_exercise_r_training_session_exercise__not_null NOT NULL,
    runtime_exercise_id bigint NOT NULL,
    run_index integer NOT NULL,
    status character varying(20) NOT NULL,
    initial_assignment_event_public_id uuid CONSTRAINT training_session_exercise_r_initial_assignment_event_p_not_null NOT NULL,
    planned_duration_ms bigint NOT NULL,
    active_duration_ms bigint NOT NULL,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    client_revision bigint NOT NULL,
    writer_instance_id uuid NOT NULL,
    writer_epoch integer NOT NULL,
    payload_hash character varying(64) NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_training_exercise_run_client_revision CHECK ((client_revision >= 1)),
    CONSTRAINT ck_training_exercise_run_durations CHECK (((planned_duration_ms >= 0) AND (active_duration_ms >= 0))),
    CONSTRAINT ck_training_exercise_run_index CHECK ((run_index >= 1)),
    CONSTRAINT ck_training_exercise_run_status CHECK (((status)::text = ANY ((ARRAY['READY'::character varying, 'ACTIVE'::character varying, 'PAUSED'::character varying, 'COMPLETED'::character varying, 'ABANDONED'::character varying])::text[]))),
    CONSTRAINT ck_training_exercise_run_timestamps CHECK (((((status)::text = 'READY'::text) AND (active_duration_ms = 0) AND (started_at IS NULL) AND (ended_at IS NULL)) OR (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'PAUSED'::character varying])::text[])) AND (started_at IS NOT NULL) AND (ended_at IS NULL)) OR (((status)::text = 'COMPLETED'::text) AND (started_at IS NOT NULL) AND (ended_at IS NOT NULL)) OR (((status)::text = 'ABANDONED'::text) AND (ended_at IS NOT NULL) AND ((started_at IS NOT NULL) OR (active_duration_ms = 0)))))
);


--
-- Name: training_session_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_id_seq OWNED BY public.training_session.id;


--
-- Name: training_session_module; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_module (
    id bigint NOT NULL,
    training_session_id bigint NOT NULL,
    runtime_module_id bigint NOT NULL,
    source_module_id bigint,
    source_scenario_day_module_id bigint,
    client_uid character varying(36) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    day_index integer,
    duration_minutes integer,
    content_subcolumn_id_snapshot bigint,
    content_subcolumn_name_snapshot character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_training_session_module_day_index CHECK (((day_index IS NULL) OR (day_index >= 1))),
    CONSTRAINT ck_training_session_module_duration_minutes CHECK (((duration_minutes IS NULL) OR (duration_minutes >= 0))),
    CONSTRAINT ck_training_session_module_order_index CHECK ((order_index >= 0))
);


--
-- Name: training_session_module_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_module_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_module_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_module_id_seq OWNED BY public.training_session_module.id;


--
-- Name: training_session_scenario_pdf; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session_scenario_pdf (
    id bigint NOT NULL,
    training_session_id bigint NOT NULL,
    source_scenario_pdf_id bigint,
    storage_key character varying(128) NOT NULL,
    storage_path character varying(2048) NOT NULL,
    original_filename character varying(512) NOT NULL,
    display_name character varying(255),
    content_type character varying(255) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    order_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_training_session_scenario_pdf_order_index CHECK ((order_index >= 0))
);


--
-- Name: training_session_scenario_pdf_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_session_scenario_pdf_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_session_scenario_pdf_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_session_scenario_pdf_id_seq OWNED BY public.training_session_scenario_pdf.id;


--
-- Name: user_aircraft; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_aircraft (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    aircraft_id bigint NOT NULL
);


--
-- Name: user_aircraft_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_aircraft_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_aircraft_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_aircraft_id_seq OWNED BY public.user_aircraft.id;


--
-- Name: user_info; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_info (
    id bigint NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    license_number character varying(50),
    phone character varying(30),
    photo_url character varying(500),
    photo_storage_path character varying(2048),
    photo_storage_key character varying(128),
    photo_content_type character varying(255),
    photo_size_bytes bigint,
    photo_sha256 character varying(64),
    signature_url character varying(500),
    signature_storage_path character varying(2048),
    signature_storage_key character varying(128),
    signature_content_type character varying(255),
    signature_size_bytes bigint,
    signature_sha256 character varying(64),
    date_of_birth date,
    position_id bigint
);


--
-- Name: user_recurrent_compliance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_recurrent_compliance (
    user_id bigint NOT NULL,
    compliance_id bigint NOT NULL
);


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_roles (
    user_id bigint NOT NULL,
    role_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    public_id uuid NOT NULL,
    login character varying(50) NOT NULL,
    email character varying(255) NOT NULL,
    hashed_password character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    must_change_password boolean DEFAULT false NOT NULL,
    airline_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: ai_review id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_review ALTER COLUMN id SET DEFAULT nextval('public.ai_review_id_seq'::regclass);


--
-- Name: ai_scenario_approval_token id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_approval_token ALTER COLUMN id SET DEFAULT nextval('public.ai_scenario_approval_token_id_seq'::regclass);


--
-- Name: ai_scenario_event id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_event ALTER COLUMN id SET DEFAULT nextval('public.ai_scenario_event_id_seq'::regclass);


--
-- Name: ai_scenario_job id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job ALTER COLUMN id SET DEFAULT nextval('public.ai_scenario_job_id_seq'::regclass);


--
-- Name: ai_scenario_job_step id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job_step ALTER COLUMN id SET DEFAULT nextval('public.ai_scenario_job_step_id_seq'::regclass);


--
-- Name: aircraft_airline id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aircraft_airline ALTER COLUMN id SET DEFAULT nextval('public.aircraft_airline_id_seq'::regclass);


--
-- Name: airline id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.airline ALTER COLUMN id SET DEFAULT nextval('public.airline_id_seq'::regclass);


--
-- Name: airline_position id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.airline_position ALTER COLUMN id SET DEFAULT nextval('public.airline_position_id_seq'::regclass);


--
-- Name: behavioural_indicator id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.behavioural_indicator ALTER COLUMN id SET DEFAULT nextval('public.behavioural_indicator_id_seq'::regclass);


--
-- Name: block_folder id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder ALTER COLUMN id SET DEFAULT nextval('public.block_folder_id_seq'::regclass);


--
-- Name: block_folder_item id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder_item ALTER COLUMN id SET DEFAULT nextval('public.block_folder_item_id_seq'::regclass);


--
-- Name: competence id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competence ALTER COLUMN id SET DEFAULT nextval('public.competence_id_seq'::regclass);


--
-- Name: crew_member_assessment id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_member_assessment ALTER COLUMN id SET DEFAULT nextval('public.crew_member_assessment_id_seq'::regclass);


--
-- Name: element id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element ALTER COLUMN id SET DEFAULT nextval('public.element_id_seq'::regclass);


--
-- Name: element_block id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block ALTER COLUMN id SET DEFAULT nextval('public.element_block_id_seq'::regclass);


--
-- Name: element_block_competence id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_competence ALTER COLUMN id SET DEFAULT nextval('public.element_block_competence_id_seq'::regclass);


--
-- Name: element_block_element id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_element ALTER COLUMN id SET DEFAULT nextval('public.element_block_element_id_seq'::regclass);


--
-- Name: element_block_param id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_param ALTER COLUMN id SET DEFAULT nextval('public.element_block_param_id_seq'::regclass);


--
-- Name: element_folder id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder ALTER COLUMN id SET DEFAULT nextval('public.element_folder_id_seq'::regclass);


--
-- Name: element_folder_item id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder_item ALTER COLUMN id SET DEFAULT nextval('public.element_folder_item_id_seq'::regclass);


--
-- Name: exercise id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise ALTER COLUMN id SET DEFAULT nextval('public.exercise_id_seq'::regclass);


--
-- Name: exercise_competence id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_competence ALTER COLUMN id SET DEFAULT nextval('public.exercise_competence_id_seq'::regclass);


--
-- Name: exercise_element id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_element ALTER COLUMN id SET DEFAULT nextval('public.exercise_element_id_seq'::regclass);


--
-- Name: exercise_image id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_image ALTER COLUMN id SET DEFAULT nextval('public.exercise_image_id_seq'::regclass);


--
-- Name: exercise_param id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_param ALTER COLUMN id SET DEFAULT nextval('public.exercise_param_id_seq'::regclass);


--
-- Name: feedback_attachment id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_attachment ALTER COLUMN id SET DEFAULT nextval('public.feedback_attachment_id_seq'::regclass);


--
-- Name: feedback_ticket id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_ticket ALTER COLUMN id SET DEFAULT nextval('public.feedback_ticket_id_seq'::regclass);


--
-- Name: final_report id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.final_report ALTER COLUMN id SET DEFAULT nextval('public.final_report_id_seq'::regclass);


--
-- Name: flight_type id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type ALTER COLUMN id SET DEFAULT nextval('public.flight_type_id_seq'::regclass);


--
-- Name: flight_type_competence_threshold id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type_competence_threshold ALTER COLUMN id SET DEFAULT nextval('public.flight_type_competence_threshold_id_seq'::regclass);


--
-- Name: grading_scale_value id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scale_value ALTER COLUMN id SET DEFAULT nextval('public.grading_scale_value_id_seq'::regclass);


--
-- Name: grading_scheme id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scheme ALTER COLUMN id SET DEFAULT nextval('public.grading_scheme_id_seq'::regclass);


--
-- Name: mistake_report id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mistake_report ALTER COLUMN id SET DEFAULT nextval('public.mistake_report_id_seq'::regclass);


--
-- Name: module id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module ALTER COLUMN id SET DEFAULT nextval('public.module_id_seq'::regclass);


--
-- Name: privileges id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.privileges ALTER COLUMN id SET DEFAULT nextval('public.privileges_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: scenario id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario ALTER COLUMN id SET DEFAULT nextval('public.scenario_id_seq'::regclass);


--
-- Name: scenario_content_cell id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_cell ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_cell_id_seq'::regclass);


--
-- Name: scenario_content_folder id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_folder ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_folder_id_seq'::regclass);


--
-- Name: scenario_content_requirement id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_requirement_id_seq'::regclass);


--
-- Name: scenario_content_requirement_element id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement_element ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_requirement_element_id_seq'::regclass);


--
-- Name: scenario_content_set id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_set_id_seq'::regclass);


--
-- Name: scenario_content_set_label id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_set_label_id_seq'::regclass);


--
-- Name: scenario_content_set_label_scenario id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label_scenario ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_set_label_scenario_id_seq'::regclass);


--
-- Name: scenario_content_subcolumn id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_subcolumn ALTER COLUMN id SET DEFAULT nextval('public.scenario_content_subcolumn_id_seq'::regclass);


--
-- Name: scenario_day_module id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_day_module ALTER COLUMN id SET DEFAULT nextval('public.scenario_day_module_id_seq'::regclass);


--
-- Name: scenario_edit_lock id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_edit_lock ALTER COLUMN id SET DEFAULT nextval('public.scenario_edit_lock_id_seq'::regclass);


--
-- Name: scenario_pdf id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_pdf ALTER COLUMN id SET DEFAULT nextval('public.scenario_pdf_id_seq'::regclass);


--
-- Name: scenario_revision id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_revision ALTER COLUMN id SET DEFAULT nextval('public.scenario_revision_id_seq'::regclass);


--
-- Name: speech_diarization_block id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_diarization_block ALTER COLUMN id SET DEFAULT nextval('public.speech_diarization_block_id_seq'::regclass);


--
-- Name: speech_review id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_review ALTER COLUMN id SET DEFAULT nextval('public.speech_review_id_seq'::regclass);


--
-- Name: speech_session_chunk id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session_chunk ALTER COLUMN id SET DEFAULT nextval('public.speech_session_chunk_id_seq'::regclass);


--
-- Name: speech_speaker_profile id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_speaker_profile ALTER COLUMN id SET DEFAULT nextval('public.speech_speaker_profile_id_seq'::regclass);


--
-- Name: speech_transcript_segment id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_transcript_segment ALTER COLUMN id SET DEFAULT nextval('public.speech_transcript_segment_id_seq'::regclass);


--
-- Name: take_off_landing_param id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.take_off_landing_param ALTER COLUMN id SET DEFAULT nextval('public.take_off_landing_param_id_seq'::regclass);


--
-- Name: training_session id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session ALTER COLUMN id SET DEFAULT nextval('public.training_session_id_seq'::regclass);


--
-- Name: training_session_crew_assignment_event id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event ALTER COLUMN id SET DEFAULT nextval('public.training_session_crew_assignment_event_id_seq'::regclass);


--
-- Name: training_session_draft id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_draft ALTER COLUMN id SET DEFAULT nextval('public.training_session_draft_id_seq'::regclass);


--
-- Name: training_session_exercise id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise ALTER COLUMN id SET DEFAULT nextval('public.training_session_exercise_id_seq'::regclass);


--
-- Name: training_session_exercise_competence id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_competence ALTER COLUMN id SET DEFAULT nextval('public.training_session_exercise_competence_id_seq'::regclass);


--
-- Name: training_session_exercise_crew_segment id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment ALTER COLUMN id SET DEFAULT nextval('public.training_session_exercise_crew_segment_id_seq'::regclass);


--
-- Name: training_session_exercise_element id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_element ALTER COLUMN id SET DEFAULT nextval('public.training_session_exercise_element_id_seq'::regclass);


--
-- Name: training_session_exercise_image id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_image ALTER COLUMN id SET DEFAULT nextval('public.training_session_exercise_image_id_seq'::regclass);


--
-- Name: training_session_module id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_module ALTER COLUMN id SET DEFAULT nextval('public.training_session_module_id_seq'::regclass);


--
-- Name: training_session_scenario_pdf id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_scenario_pdf ALTER COLUMN id SET DEFAULT nextval('public.training_session_scenario_pdf_id_seq'::regclass);


--
-- Name: user_aircraft id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_aircraft ALTER COLUMN id SET DEFAULT nextval('public.user_aircraft_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: ai_review ai_review_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_review
    ADD CONSTRAINT ai_review_pkey PRIMARY KEY (id);


--
-- Name: ai_scenario_approval_token ai_scenario_approval_token_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_approval_token
    ADD CONSTRAINT ai_scenario_approval_token_pkey PRIMARY KEY (id);


--
-- Name: ai_scenario_event ai_scenario_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_event
    ADD CONSTRAINT ai_scenario_event_pkey PRIMARY KEY (id);


--
-- Name: ai_scenario_job ai_scenario_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job
    ADD CONSTRAINT ai_scenario_job_pkey PRIMARY KEY (id);


--
-- Name: ai_scenario_job_step ai_scenario_job_step_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job_step
    ADD CONSTRAINT ai_scenario_job_step_pkey PRIMARY KEY (id);


--
-- Name: aircraft_airline aircraft_airline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aircraft_airline
    ADD CONSTRAINT aircraft_airline_pkey PRIMARY KEY (id);


--
-- Name: airline airline_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.airline
    ADD CONSTRAINT airline_code_key UNIQUE (code);


--
-- Name: airline airline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.airline
    ADD CONSTRAINT airline_pkey PRIMARY KEY (id);


--
-- Name: airline_position airline_position_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.airline_position
    ADD CONSTRAINT airline_position_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: auth_sessions auth_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_pkey PRIMARY KEY (id);


--
-- Name: behavioural_indicator behavioural_indicator_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.behavioural_indicator
    ADD CONSTRAINT behavioural_indicator_pkey PRIMARY KEY (id);


--
-- Name: block_folder_item block_folder_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder_item
    ADD CONSTRAINT block_folder_item_pkey PRIMARY KEY (id);


--
-- Name: block_folder block_folder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder
    ADD CONSTRAINT block_folder_pkey PRIMARY KEY (id);


--
-- Name: competence competence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competence
    ADD CONSTRAINT competence_pkey PRIMARY KEY (id);


--
-- Name: crew_member_assessment crew_member_assessment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_member_assessment
    ADD CONSTRAINT crew_member_assessment_pkey PRIMARY KEY (id);


--
-- Name: element_block_competence element_block_competence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_competence
    ADD CONSTRAINT element_block_competence_pkey PRIMARY KEY (id);


--
-- Name: element_block element_block_element_block_param_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block
    ADD CONSTRAINT element_block_element_block_param_id_key UNIQUE (element_block_param_id);


--
-- Name: element_block_element element_block_element_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_element
    ADD CONSTRAINT element_block_element_pkey PRIMARY KEY (id);


--
-- Name: element_block_param element_block_param_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_param
    ADD CONSTRAINT element_block_param_pkey PRIMARY KEY (id);


--
-- Name: element_block element_block_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block
    ADD CONSTRAINT element_block_pkey PRIMARY KEY (id);


--
-- Name: element_folder_item element_folder_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder_item
    ADD CONSTRAINT element_folder_item_pkey PRIMARY KEY (id);


--
-- Name: element_folder element_folder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder
    ADD CONSTRAINT element_folder_pkey PRIMARY KEY (id);


--
-- Name: element element_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element
    ADD CONSTRAINT element_pkey PRIMARY KEY (id);


--
-- Name: exercise_competence exercise_competence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_competence
    ADD CONSTRAINT exercise_competence_pkey PRIMARY KEY (id);


--
-- Name: exercise_element exercise_element_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_element
    ADD CONSTRAINT exercise_element_pkey PRIMARY KEY (id);


--
-- Name: exercise exercise_exercise_param_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise
    ADD CONSTRAINT exercise_exercise_param_id_key UNIQUE (exercise_param_id);


--
-- Name: exercise_image exercise_image_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_image
    ADD CONSTRAINT exercise_image_pkey PRIMARY KEY (id);


--
-- Name: exercise_image exercise_image_storage_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_image
    ADD CONSTRAINT exercise_image_storage_key_key UNIQUE (storage_key);


--
-- Name: exercise_param exercise_param_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_param
    ADD CONSTRAINT exercise_param_pkey PRIMARY KEY (id);


--
-- Name: exercise exercise_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise
    ADD CONSTRAINT exercise_pkey PRIMARY KEY (id);


--
-- Name: feedback_attachment feedback_attachment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_attachment
    ADD CONSTRAINT feedback_attachment_pkey PRIMARY KEY (id);


--
-- Name: feedback_ticket feedback_ticket_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_ticket
    ADD CONSTRAINT feedback_ticket_pkey PRIMARY KEY (id);


--
-- Name: final_report final_report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.final_report
    ADD CONSTRAINT final_report_pkey PRIMARY KEY (id);


--
-- Name: flight_type_competence_threshold flight_type_competence_threshold_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type_competence_threshold
    ADD CONSTRAINT flight_type_competence_threshold_pkey PRIMARY KEY (id);


--
-- Name: flight_type flight_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type
    ADD CONSTRAINT flight_type_pkey PRIMARY KEY (id);


--
-- Name: grading_scale_value grading_scale_value_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scale_value
    ADD CONSTRAINT grading_scale_value_pkey PRIMARY KEY (id);


--
-- Name: grading_scheme grading_scheme_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scheme
    ADD CONSTRAINT grading_scheme_pkey PRIMARY KEY (id);


--
-- Name: mistake_report mistake_report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mistake_report
    ADD CONSTRAINT mistake_report_pkey PRIMARY KEY (id);


--
-- Name: module module_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module
    ADD CONSTRAINT module_pkey PRIMARY KEY (id);


--
-- Name: privileges privileges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.privileges
    ADD CONSTRAINT privileges_pkey PRIMARY KEY (id);


--
-- Name: role_privileges role_privileges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_privileges
    ADD CONSTRAINT role_privileges_pkey PRIMARY KEY (role_id, privilege_id);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_cell scenario_content_cell_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_cell
    ADD CONSTRAINT scenario_content_cell_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_folder scenario_content_folder_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_folder
    ADD CONSTRAINT scenario_content_folder_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_requirement_element scenario_content_requirement_element_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement_element
    ADD CONSTRAINT scenario_content_requirement_element_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_requirement scenario_content_requirement_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement
    ADD CONSTRAINT scenario_content_requirement_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_set_label scenario_content_set_label_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label
    ADD CONSTRAINT scenario_content_set_label_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_set_label_scenario scenario_content_set_label_scenario_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label_scenario
    ADD CONSTRAINT scenario_content_set_label_scenario_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_set scenario_content_set_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set
    ADD CONSTRAINT scenario_content_set_pkey PRIMARY KEY (id);


--
-- Name: scenario_content_subcolumn scenario_content_subcolumn_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_subcolumn
    ADD CONSTRAINT scenario_content_subcolumn_pkey PRIMARY KEY (id);


--
-- Name: scenario_day_module scenario_day_module_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_day_module
    ADD CONSTRAINT scenario_day_module_pkey PRIMARY KEY (id);


--
-- Name: scenario_edit_lock scenario_edit_lock_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_edit_lock
    ADD CONSTRAINT scenario_edit_lock_pkey PRIMARY KEY (id);


--
-- Name: scenario_pdf scenario_pdf_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_pdf
    ADD CONSTRAINT scenario_pdf_pkey PRIMARY KEY (id);


--
-- Name: scenario_pdf scenario_pdf_storage_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_pdf
    ADD CONSTRAINT scenario_pdf_storage_key_key UNIQUE (storage_key);


--
-- Name: scenario scenario_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario
    ADD CONSTRAINT scenario_pkey PRIMARY KEY (id);


--
-- Name: scenario_revision scenario_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_revision
    ADD CONSTRAINT scenario_revision_pkey PRIMARY KEY (id);


--
-- Name: speech_artifact speech_artifact_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_artifact
    ADD CONSTRAINT speech_artifact_pkey PRIMARY KEY (id);


--
-- Name: speech_diarization_block speech_diarization_block_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_diarization_block
    ADD CONSTRAINT speech_diarization_block_pkey PRIMARY KEY (id);


--
-- Name: speech_external_job speech_external_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_external_job
    ADD CONSTRAINT speech_external_job_pkey PRIMARY KEY (id);


--
-- Name: speech_external_job speech_external_job_provider_job_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_external_job
    ADD CONSTRAINT speech_external_job_provider_job_id_key UNIQUE (provider_job_id);


--
-- Name: speech_review speech_review_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_review
    ADD CONSTRAINT speech_review_pkey PRIMARY KEY (id);


--
-- Name: speech_session_chunk speech_session_chunk_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session_chunk
    ADD CONSTRAINT speech_session_chunk_pkey PRIMARY KEY (id);


--
-- Name: speech_session speech_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session
    ADD CONSTRAINT speech_session_pkey PRIMARY KEY (id);


--
-- Name: speech_speaker_profile speech_speaker_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_speaker_profile
    ADD CONSTRAINT speech_speaker_profile_pkey PRIMARY KEY (id);


--
-- Name: speech_transcript_segment speech_transcript_segment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_transcript_segment
    ADD CONSTRAINT speech_transcript_segment_pkey PRIMARY KEY (id);


--
-- Name: take_off_landing_param take_off_landing_param_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.take_off_landing_param
    ADD CONSTRAINT take_off_landing_param_pkey PRIMARY KEY (id);


--
-- Name: takeoff_param_details takeoff_param_details_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.takeoff_param_details
    ADD CONSTRAINT takeoff_param_details_pkey PRIMARY KEY (take_off_landing_param_id);


--
-- Name: training_session_crew_assignment_event training_session_crew_assignment_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT training_session_crew_assignment_event_pkey PRIMARY KEY (id);


--
-- Name: training_session_crew_assignment_event training_session_crew_assignment_event_public_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT training_session_crew_assignment_event_public_id_key UNIQUE (public_id);


--
-- Name: training_session_crew_state training_session_crew_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_state
    ADD CONSTRAINT training_session_crew_state_pkey PRIMARY KEY (training_session_id);


--
-- Name: training_session_draft training_session_draft_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_draft
    ADD CONSTRAINT training_session_draft_pkey PRIMARY KEY (id);


--
-- Name: training_session_exercise_competence training_session_exercise_competence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_competence
    ADD CONSTRAINT training_session_exercise_competence_pkey PRIMARY KEY (id);


--
-- Name: training_session_exercise_crew_segment training_session_exercise_crew_segment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT training_session_exercise_crew_segment_pkey PRIMARY KEY (id);


--
-- Name: training_session_exercise_element training_session_exercise_element_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_element
    ADD CONSTRAINT training_session_exercise_element_pkey PRIMARY KEY (id);


--
-- Name: training_session_exercise_image training_session_exercise_image_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_image
    ADD CONSTRAINT training_session_exercise_image_pkey PRIMARY KEY (id);


--
-- Name: training_session_exercise training_session_exercise_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise
    ADD CONSTRAINT training_session_exercise_pkey PRIMARY KEY (id);


--
-- Name: training_session_exercise_run training_session_exercise_run_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_run
    ADD CONSTRAINT training_session_exercise_run_pkey PRIMARY KEY (exercise_session_key);


--
-- Name: training_session_module training_session_module_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_module
    ADD CONSTRAINT training_session_module_pkey PRIMARY KEY (id);


--
-- Name: training_session training_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session
    ADD CONSTRAINT training_session_pkey PRIMARY KEY (id);


--
-- Name: training_session_scenario_pdf training_session_scenario_pdf_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_scenario_pdf
    ADD CONSTRAINT training_session_scenario_pdf_pkey PRIMARY KEY (id);


--
-- Name: ai_scenario_approval_token uq_ai_scenario_approval_token_job_event_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_approval_token
    ADD CONSTRAINT uq_ai_scenario_approval_token_job_event_sequence UNIQUE (job_id, event_sequence);


--
-- Name: ai_scenario_approval_token uq_ai_scenario_approval_token_token; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_approval_token
    ADD CONSTRAINT uq_ai_scenario_approval_token_token UNIQUE (token);


--
-- Name: ai_scenario_event uq_ai_scenario_event_job_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_event
    ADD CONSTRAINT uq_ai_scenario_event_job_sequence UNIQUE (job_id, sequence);


--
-- Name: ai_scenario_job_step uq_ai_scenario_job_step_job_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job_step
    ADD CONSTRAINT uq_ai_scenario_job_step_job_sequence UNIQUE (job_id, sequence);


--
-- Name: ai_scenario_job_step uq_ai_scenario_job_step_job_step_input_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job_step
    ADD CONSTRAINT uq_ai_scenario_job_step_job_step_input_hash UNIQUE (job_id, step_key, input_hash);


--
-- Name: aircraft_airline uq_aircraft_airline_airline_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aircraft_airline
    ADD CONSTRAINT uq_aircraft_airline_airline_code UNIQUE (airline_id, code);


--
-- Name: airline_position uq_airline_position_airline_normalized_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.airline_position
    ADD CONSTRAINT uq_airline_position_airline_normalized_name UNIQUE (airline_id, normalized_name);


--
-- Name: auth_sessions uq_auth_sessions_refresh_jti; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT uq_auth_sessions_refresh_jti UNIQUE (refresh_jti);


--
-- Name: behavioural_indicator uq_behavioural_indicator_competence_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.behavioural_indicator
    ADD CONSTRAINT uq_behavioural_indicator_competence_code UNIQUE (competence_id, code);


--
-- Name: competence uq_competence_airline_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competence
    ADD CONSTRAINT uq_competence_airline_code UNIQUE (airline_id, code);


--
-- Name: scenario_content_cell uq_content_cell; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_cell
    ADD CONSTRAINT uq_content_cell UNIQUE (requirement_id, set_label_id, subcolumn_id);


--
-- Name: scenario_content_requirement_element uq_content_requirement_element; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement_element
    ADD CONSTRAINT uq_content_requirement_element UNIQUE (requirement_id, element_id);


--
-- Name: scenario_content_set_label uq_content_set_label; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label
    ADD CONSTRAINT uq_content_set_label UNIQUE (content_set_id, label);


--
-- Name: scenario_content_set_label_scenario uq_content_set_label_scenario; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label_scenario
    ADD CONSTRAINT uq_content_set_label_scenario UNIQUE (label_id, scenario_id);


--
-- Name: scenario_content_subcolumn uq_content_subcolumn_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_subcolumn
    ADD CONSTRAINT uq_content_subcolumn_name UNIQUE (content_set_id, name);


--
-- Name: crew_member_assessment uq_crew_member_assessment_training_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_member_assessment
    ADD CONSTRAINT uq_crew_member_assessment_training_id UNIQUE (training_session_id, id);


--
-- Name: crew_member_assessment uq_crew_member_assessment_training_role; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_member_assessment
    ADD CONSTRAINT uq_crew_member_assessment_training_role UNIQUE (training_session_id, training_role);


--
-- Name: crew_member_assessment uq_crew_member_assessment_training_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_member_assessment
    ADD CONSTRAINT uq_crew_member_assessment_training_user UNIQUE (training_session_id, user_id);


--
-- Name: flight_type uq_flight_type_airline_normalized_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type
    ADD CONSTRAINT uq_flight_type_airline_normalized_name UNIQUE (airline_id, normalized_name);


--
-- Name: flight_type_competence_threshold uq_flight_type_competence_threshold_flight_type_competence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type_competence_threshold
    ADD CONSTRAINT uq_flight_type_competence_threshold_flight_type_competence UNIQUE (flight_type_id, competence_id);


--
-- Name: grading_scale_value uq_grading_scale_value_scheme_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scale_value
    ADD CONSTRAINT uq_grading_scale_value_scheme_code UNIQUE (grading_scheme_id, code);


--
-- Name: grading_scale_value uq_grading_scale_value_scheme_order_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scale_value
    ADD CONSTRAINT uq_grading_scale_value_scheme_order_index UNIQUE (grading_scheme_id, order_index);


--
-- Name: grading_scheme uq_grading_scheme_airline_name_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scheme
    ADD CONSTRAINT uq_grading_scheme_airline_name_version UNIQUE (airline_id, name, version);


--
-- Name: privileges uq_privileges_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.privileges
    ADD CONSTRAINT uq_privileges_name UNIQUE (name);


--
-- Name: roles uq_roles_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_roles_name UNIQUE (name);


--
-- Name: scenario_day_module uq_scenario_day_module_module; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_day_module
    ADD CONSTRAINT uq_scenario_day_module_module UNIQUE (module_id);


--
-- Name: scenario_day_module uq_scenario_day_module_scenario_module; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_day_module
    ADD CONSTRAINT uq_scenario_day_module_scenario_module UNIQUE (scenario_id, module_id);


--
-- Name: scenario_edit_lock uq_scenario_edit_lock_scenario; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_edit_lock
    ADD CONSTRAINT uq_scenario_edit_lock_scenario UNIQUE (scenario_id);


--
-- Name: scenario_revision uq_scenario_revision_client_entry; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_revision
    ADD CONSTRAINT uq_scenario_revision_client_entry UNIQUE (scenario_id, client_entry_id);


--
-- Name: scenario_revision uq_scenario_revision_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_revision
    ADD CONSTRAINT uq_scenario_revision_number UNIQUE (scenario_id, revision_number);


--
-- Name: speech_artifact uq_speech_artifact_session_type_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_artifact
    ADD CONSTRAINT uq_speech_artifact_session_type_path UNIQUE (session_id, type, path);


--
-- Name: speech_diarization_block uq_speech_diarization_block; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_diarization_block
    ADD CONSTRAINT uq_speech_diarization_block UNIQUE (session_id, block_index);


--
-- Name: speech_review uq_speech_review_session; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_review
    ADD CONSTRAINT uq_speech_review_session UNIQUE (session_id);


--
-- Name: speech_session_chunk uq_speech_session_chunk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session_chunk
    ADD CONSTRAINT uq_speech_session_chunk UNIQUE (session_id, chunk_index);


--
-- Name: speech_speaker_profile uq_speech_speaker_profile; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_speaker_profile
    ADD CONSTRAINT uq_speech_speaker_profile UNIQUE (session_id, pilot);


--
-- Name: training_session_crew_assignment_event uq_training_crew_event_training_public; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT uq_training_crew_event_training_public UNIQUE (training_session_id, public_id);


--
-- Name: training_session_crew_assignment_event uq_training_crew_event_training_revision; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT uq_training_crew_event_training_revision UNIQUE (training_session_id, server_revision);


--
-- Name: training_session_crew_assignment_event uq_training_crew_event_writer_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT uq_training_crew_event_writer_sequence UNIQUE (training_session_id, writer_epoch, client_sequence);


--
-- Name: training_session_exercise_crew_segment uq_training_crew_segment_run_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT uq_training_crew_segment_run_index UNIQUE (exercise_session_key, segment_index);


--
-- Name: training_session_exercise_run uq_training_exercise_run_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_run
    ADD CONSTRAINT uq_training_exercise_run_index UNIQUE (training_session_id, training_session_exercise_id, run_index);


--
-- Name: training_session_exercise_run uq_training_exercise_run_training_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_run
    ADD CONSTRAINT uq_training_exercise_run_training_key UNIQUE (training_session_id, exercise_session_key);


--
-- Name: training_session_exercise_run uq_training_exercise_run_training_key_exercise; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_run
    ADD CONSTRAINT uq_training_exercise_run_training_key_exercise UNIQUE (training_session_id, exercise_session_key, training_session_exercise_id);


--
-- Name: training_session_draft uq_training_session_draft_training_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_draft
    ADD CONSTRAINT uq_training_session_draft_training_user UNIQUE (training_session_id, user_id);


--
-- Name: training_session_exercise uq_training_session_exercise_runtime_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise
    ADD CONSTRAINT uq_training_session_exercise_runtime_id UNIQUE (training_session_id, runtime_exercise_id);


--
-- Name: training_session_exercise uq_training_session_exercise_training_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise
    ADD CONSTRAINT uq_training_session_exercise_training_id UNIQUE (training_session_id, id);


--
-- Name: training_session_exercise uq_training_session_exercise_training_id_runtime; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise
    ADD CONSTRAINT uq_training_session_exercise_training_id_runtime UNIQUE (training_session_id, id, runtime_exercise_id);


--
-- Name: training_session uq_training_session_instructor_client_creation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session
    ADD CONSTRAINT uq_training_session_instructor_client_creation UNIQUE (instructor_id, client_creation_id);


--
-- Name: training_session_module uq_training_session_module_runtime_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_module
    ADD CONSTRAINT uq_training_session_module_runtime_id UNIQUE (training_session_id, runtime_module_id);


--
-- Name: user_aircraft uq_user_aircraft_user_aircraft_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_aircraft
    ADD CONSTRAINT uq_user_aircraft_user_aircraft_id UNIQUE (user_id, aircraft_id);


--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);


--
-- Name: users uq_users_login; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_login UNIQUE (login);


--
-- Name: user_aircraft user_aircraft_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_aircraft
    ADD CONSTRAINT user_aircraft_pkey PRIMARY KEY (id);


--
-- Name: user_info user_info_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_info
    ADD CONSTRAINT user_info_pkey PRIMARY KEY (id);


--
-- Name: user_recurrent_compliance user_recurrent_compliance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recurrent_compliance
    ADD CONSTRAINT user_recurrent_compliance_pkey PRIMARY KEY (user_id);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_ai_review_assessment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_review_assessment_id ON public.ai_review USING btree (assessment_id);


--
-- Name: ix_ai_review_competence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_review_competence_id ON public.ai_review USING btree (competence_id);


--
-- Name: ix_ai_scenario_approval_token_consumed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_approval_token_consumed_at ON public.ai_scenario_approval_token USING btree (consumed_at);


--
-- Name: ix_ai_scenario_approval_token_consumed_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_approval_token_consumed_by_user_id ON public.ai_scenario_approval_token USING btree (consumed_by_user_id);


--
-- Name: ix_ai_scenario_approval_token_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_approval_token_event_id ON public.ai_scenario_approval_token USING btree (event_id);


--
-- Name: ix_ai_scenario_approval_token_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_approval_token_expires_at ON public.ai_scenario_approval_token USING btree (expires_at);


--
-- Name: ix_ai_scenario_approval_token_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_approval_token_job_id ON public.ai_scenario_approval_token USING btree (job_id);


--
-- Name: ix_ai_scenario_approval_token_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_approval_token_status ON public.ai_scenario_approval_token USING btree (status);


--
-- Name: ix_ai_scenario_event_event_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_event_event_name ON public.ai_scenario_event USING btree (event_name);


--
-- Name: ix_ai_scenario_event_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_event_job_id ON public.ai_scenario_event USING btree (job_id);


--
-- Name: ix_ai_scenario_event_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_event_status ON public.ai_scenario_event USING btree (status);


--
-- Name: ix_ai_scenario_job_celery_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_celery_task_id ON public.ai_scenario_job USING btree (celery_task_id);


--
-- Name: ix_ai_scenario_job_scenario_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_scenario_id ON public.ai_scenario_job USING btree (scenario_id);


--
-- Name: ix_ai_scenario_job_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_status ON public.ai_scenario_job USING btree (status);


--
-- Name: ix_ai_scenario_job_step_agent_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_step_agent_name ON public.ai_scenario_job_step USING btree (agent_name);


--
-- Name: ix_ai_scenario_job_step_input_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_step_input_hash ON public.ai_scenario_job_step USING btree (input_hash);


--
-- Name: ix_ai_scenario_job_step_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_step_job_id ON public.ai_scenario_job_step USING btree (job_id);


--
-- Name: ix_ai_scenario_job_step_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_step_status ON public.ai_scenario_job_step USING btree (status);


--
-- Name: ix_ai_scenario_job_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_scenario_job_user_id ON public.ai_scenario_job USING btree (user_id);


--
-- Name: ix_aircraft_airline_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aircraft_airline_airline_id ON public.aircraft_airline USING btree (airline_id);


--
-- Name: ix_airline_position_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_airline_position_airline_id ON public.airline_position USING btree (airline_id);


--
-- Name: ix_auth_sessions_refresh_jti; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_sessions_refresh_jti ON public.auth_sessions USING btree (refresh_jti);


--
-- Name: ix_auth_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_sessions_user_id ON public.auth_sessions USING btree (user_id);


--
-- Name: ix_behavioural_indicator_competence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_behavioural_indicator_competence_id ON public.behavioural_indicator USING btree (competence_id);


--
-- Name: ix_block_folder_aircraft_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_block_folder_aircraft_id ON public.block_folder USING btree (aircraft_id);


--
-- Name: ix_block_folder_archived_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_block_folder_archived_at ON public.block_folder USING btree (archived_at);


--
-- Name: ix_block_folder_archived_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_block_folder_archived_by ON public.block_folder USING btree (archived_by);


--
-- Name: ix_block_folder_item_folder_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_block_folder_item_folder_id ON public.block_folder_item USING btree (folder_id);


--
-- Name: ix_competence_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competence_airline_id ON public.competence USING btree (airline_id);


--
-- Name: ix_crew_member_assessment_signature_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_crew_member_assessment_signature_storage_key ON public.crew_member_assessment USING btree (signature_storage_key);


--
-- Name: ix_crew_member_assessment_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_crew_member_assessment_training_session_id ON public.crew_member_assessment USING btree (training_session_id);


--
-- Name: ix_crew_member_assessment_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_crew_member_assessment_user_id ON public.crew_member_assessment USING btree (user_id);


--
-- Name: ix_element_aircraft_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_aircraft_id ON public.element USING btree (aircraft_id);


--
-- Name: ix_element_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_airline_id ON public.element USING btree (airline_id);


--
-- Name: ix_element_archived_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_archived_at ON public.element USING btree (archived_at);


--
-- Name: ix_element_archived_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_archived_by ON public.element USING btree (archived_by);


--
-- Name: ix_element_block_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_block_airline_id ON public.element_block USING btree (airline_id);


--
-- Name: ix_element_block_archived_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_block_archived_at ON public.element_block USING btree (archived_at);


--
-- Name: ix_element_block_archived_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_block_archived_by ON public.element_block USING btree (archived_by);


--
-- Name: ix_element_folder_aircraft_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_folder_aircraft_id ON public.element_folder USING btree (aircraft_id);


--
-- Name: ix_element_folder_archived_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_folder_archived_at ON public.element_folder USING btree (archived_at);


--
-- Name: ix_element_folder_archived_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_folder_archived_by ON public.element_folder USING btree (archived_by);


--
-- Name: ix_element_folder_item_folder_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_element_folder_item_folder_id ON public.element_folder_item USING btree (folder_id);


--
-- Name: ix_exercise_client_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_exercise_client_uid ON public.exercise USING btree (client_uid);


--
-- Name: ix_exercise_image_exercise_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exercise_image_exercise_id ON public.exercise_image USING btree (exercise_id);


--
-- Name: ix_exercise_image_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exercise_image_storage_key ON public.exercise_image USING btree (storage_key);


--
-- Name: ix_final_report_assessment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_final_report_assessment_id ON public.final_report USING btree (assessment_id);


--
-- Name: ix_final_report_competence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_final_report_competence_id ON public.final_report USING btree (competence_id);


--
-- Name: ix_final_report_grading_scale_value_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_final_report_grading_scale_value_id ON public.final_report USING btree (grading_scale_value_id);


--
-- Name: ix_flight_type_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_flight_type_airline_id ON public.flight_type USING btree (airline_id);


--
-- Name: ix_flight_type_competence_threshold_competence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_flight_type_competence_threshold_competence_id ON public.flight_type_competence_threshold USING btree (competence_id);


--
-- Name: ix_flight_type_competence_threshold_flight_type_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_flight_type_competence_threshold_flight_type_id ON public.flight_type_competence_threshold USING btree (flight_type_id);


--
-- Name: ix_grading_scale_value_grading_scheme_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_grading_scale_value_grading_scheme_id ON public.grading_scale_value USING btree (grading_scheme_id);


--
-- Name: ix_grading_scheme_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_grading_scheme_airline_id ON public.grading_scheme USING btree (airline_id);


--
-- Name: ix_mistake_report_assessment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_assessment_id ON public.mistake_report USING btree (assessment_id);


--
-- Name: ix_mistake_report_assignment_event_id_at_observation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_assignment_event_id_at_observation ON public.mistake_report USING btree (assignment_event_id_at_observation);


--
-- Name: ix_mistake_report_behavioural_indicator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_behavioural_indicator_id ON public.mistake_report USING btree (behavioural_indicator_id);


--
-- Name: ix_mistake_report_competence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_competence_id ON public.mistake_report USING btree (competence_id);


--
-- Name: ix_mistake_report_exercise_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_exercise_id ON public.mistake_report USING btree (exercise_id);


--
-- Name: ix_mistake_report_exercise_id_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_exercise_id_timestamp ON public.mistake_report USING btree (exercise_id, "timestamp");


--
-- Name: ix_mistake_report_exercise_session_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_exercise_session_key ON public.mistake_report USING btree (exercise_session_key);


--
-- Name: ix_mistake_report_training_session_exercise_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mistake_report_training_session_exercise_id ON public.mistake_report USING btree (training_session_exercise_id);


--
-- Name: ix_module_client_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_module_client_uid ON public.module USING btree (client_uid);


--
-- Name: ix_privileges_public_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_privileges_public_id ON public.privileges USING btree (public_id);


--
-- Name: ix_roles_public_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_roles_public_id ON public.roles USING btree (public_id);


--
-- Name: ix_scenario_aircraft_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_aircraft_id ON public.scenario USING btree (aircraft_id);


--
-- Name: ix_scenario_archived_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_archived_at ON public.scenario USING btree (archived_at);


--
-- Name: ix_scenario_archived_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_archived_by ON public.scenario USING btree (archived_by);


--
-- Name: ix_scenario_content_cell_content_set_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_cell_content_set_id ON public.scenario_content_cell USING btree (content_set_id);


--
-- Name: ix_scenario_content_cell_requirement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_cell_requirement_id ON public.scenario_content_cell USING btree (requirement_id);


--
-- Name: ix_scenario_content_cell_set_label_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_cell_set_label_id ON public.scenario_content_cell USING btree (set_label_id);


--
-- Name: ix_scenario_content_cell_subcolumn_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_cell_subcolumn_id ON public.scenario_content_cell USING btree (subcolumn_id);


--
-- Name: ix_scenario_content_folder_content_set_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_folder_content_set_id ON public.scenario_content_folder USING btree (content_set_id);


--
-- Name: ix_scenario_content_folder_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_folder_parent_id ON public.scenario_content_folder USING btree (parent_id);


--
-- Name: ix_scenario_content_requirement_content_set_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_requirement_content_set_id ON public.scenario_content_requirement USING btree (content_set_id);


--
-- Name: ix_scenario_content_requirement_element_element_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_requirement_element_element_id ON public.scenario_content_requirement_element USING btree (element_id);


--
-- Name: ix_scenario_content_requirement_element_requirement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_requirement_element_requirement_id ON public.scenario_content_requirement_element USING btree (requirement_id);


--
-- Name: ix_scenario_content_requirement_folder_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_requirement_folder_id ON public.scenario_content_requirement USING btree (folder_id);


--
-- Name: ix_scenario_content_set_aircraft_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_set_aircraft_id ON public.scenario_content_set USING btree (aircraft_id);


--
-- Name: ix_scenario_content_set_airline_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_set_airline_id ON public.scenario_content_set USING btree (airline_id);


--
-- Name: ix_scenario_content_set_label_content_set_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_set_label_content_set_id ON public.scenario_content_set_label USING btree (content_set_id);


--
-- Name: ix_scenario_content_set_label_scenario_label_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_set_label_scenario_label_id ON public.scenario_content_set_label_scenario USING btree (label_id);


--
-- Name: ix_scenario_content_set_label_scenario_scenario_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_set_label_scenario_scenario_id ON public.scenario_content_set_label_scenario USING btree (scenario_id);


--
-- Name: ix_scenario_content_subcolumn_content_set_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_content_subcolumn_content_set_id ON public.scenario_content_subcolumn USING btree (content_set_id);


--
-- Name: ix_scenario_day_module_module_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_day_module_module_id ON public.scenario_day_module USING btree (module_id);


--
-- Name: ix_scenario_day_module_scenario_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_day_module_scenario_id ON public.scenario_day_module USING btree (scenario_id);


--
-- Name: ix_scenario_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_deleted_at ON public.scenario USING btree (deleted_at);


--
-- Name: ix_scenario_deleted_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_deleted_by ON public.scenario USING btree (deleted_by);


--
-- Name: ix_scenario_edit_lock_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_edit_lock_expires_at ON public.scenario_edit_lock USING btree (expires_at);


--
-- Name: ix_scenario_edit_lock_scenario_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_edit_lock_scenario_id ON public.scenario_edit_lock USING btree (scenario_id);


--
-- Name: ix_scenario_edit_lock_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_edit_lock_user_id ON public.scenario_edit_lock USING btree (user_id);


--
-- Name: ix_scenario_pdf_scenario_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_pdf_scenario_id ON public.scenario_pdf USING btree (scenario_id);


--
-- Name: ix_scenario_pdf_scenario_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_pdf_scenario_order ON public.scenario_pdf USING btree (scenario_id, order_index);


--
-- Name: ix_scenario_pdf_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_pdf_storage_key ON public.scenario_pdf USING btree (storage_key);


--
-- Name: ix_scenario_revision_branch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_branch_id ON public.scenario_revision USING btree (branch_id);


--
-- Name: ix_scenario_revision_client_created_at_ms; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_client_created_at_ms ON public.scenario_revision USING btree (client_created_at_ms);


--
-- Name: ix_scenario_revision_client_entry_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_client_entry_id ON public.scenario_revision USING btree (client_entry_id);


--
-- Name: ix_scenario_revision_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_created_by ON public.scenario_revision USING btree (created_by);


--
-- Name: ix_scenario_revision_parent_client_entry_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_parent_client_entry_id ON public.scenario_revision USING btree (parent_client_entry_id);


--
-- Name: ix_scenario_revision_parent_revision_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_parent_revision_id ON public.scenario_revision USING btree (parent_revision_id);


--
-- Name: ix_scenario_revision_scenario_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_scenario_id ON public.scenario_revision USING btree (scenario_id);


--
-- Name: ix_scenario_revision_signature; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scenario_revision_signature ON public.scenario_revision USING btree (signature);


--
-- Name: ix_speech_artifact_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_artifact_session_id ON public.speech_artifact USING btree (session_id);


--
-- Name: ix_speech_artifact_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_artifact_type ON public.speech_artifact USING btree (type);


--
-- Name: ix_speech_diarization_block_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_diarization_block_session_id ON public.speech_diarization_block USING btree (session_id);


--
-- Name: ix_speech_external_job_block_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_external_job_block_index ON public.speech_external_job USING btree (block_index);


--
-- Name: ix_speech_external_job_chunk_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_external_job_chunk_index ON public.speech_external_job USING btree (chunk_index);


--
-- Name: ix_speech_external_job_job_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_external_job_job_type ON public.speech_external_job USING btree (job_type);


--
-- Name: ix_speech_external_job_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_external_job_provider ON public.speech_external_job USING btree (provider);


--
-- Name: ix_speech_external_job_provider_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_speech_external_job_provider_job_id ON public.speech_external_job USING btree (provider_job_id);


--
-- Name: ix_speech_external_job_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_external_job_session_id ON public.speech_external_job USING btree (session_id);


--
-- Name: ix_speech_external_job_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_external_job_status ON public.speech_external_job USING btree (status);


--
-- Name: ix_speech_review_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_review_session_id ON public.speech_review USING btree (session_id);


--
-- Name: ix_speech_session_chunk_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_session_chunk_session_id ON public.speech_session_chunk USING btree (session_id);


--
-- Name: ix_speech_session_chunk_transcribe_job_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_session_chunk_transcribe_job_name ON public.speech_session_chunk USING btree (transcribe_job_name);


--
-- Name: ix_speech_session_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_session_training_session_id ON public.speech_session USING btree (training_session_id);


--
-- Name: ix_speech_session_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_session_user_id ON public.speech_session USING btree (user_id);


--
-- Name: ix_speech_speaker_profile_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_speaker_profile_session_id ON public.speech_speaker_profile USING btree (session_id);


--
-- Name: ix_speech_transcript_segment_chunk_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_transcript_segment_chunk_index ON public.speech_transcript_segment USING btree (chunk_index);


--
-- Name: ix_speech_transcript_segment_end_ms_global; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_transcript_segment_end_ms_global ON public.speech_transcript_segment USING btree (end_ms_global);


--
-- Name: ix_speech_transcript_segment_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_transcript_segment_session_id ON public.speech_transcript_segment USING btree (session_id);


--
-- Name: ix_speech_transcript_segment_start_ms_global; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_speech_transcript_segment_start_ms_global ON public.speech_transcript_segment USING btree (start_ms_global);


--
-- Name: ix_training_crew_event_run_revision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_crew_event_run_revision ON public.training_session_crew_assignment_event USING btree (exercise_session_key, server_revision);


--
-- Name: ix_training_crew_event_training_received; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_crew_event_training_received ON public.training_session_crew_assignment_event USING btree (training_session_id, received_at);


--
-- Name: ix_training_session_aircraft_id_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_aircraft_id_snapshot ON public.training_session USING btree (aircraft_id_snapshot);


--
-- Name: ix_training_session_crew_assignment_event_cm1_assessmen_2254; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_crew_assignment_event_cm1_assessmen_2254 ON public.training_session_crew_assignment_event USING btree (cm1_assessment_id_after);


--
-- Name: ix_training_session_crew_assignment_event_cm2_assessmen_454f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_crew_assignment_event_cm2_assessmen_454f ON public.training_session_crew_assignment_event USING btree (cm2_assessment_id_after);


--
-- Name: ix_training_session_crew_assignment_event_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_crew_assignment_event_created_by ON public.training_session_crew_assignment_event USING btree (created_by);


--
-- Name: ix_training_session_crew_assignment_event_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_crew_assignment_event_training_session_id ON public.training_session_crew_assignment_event USING btree (training_session_id);


--
-- Name: ix_training_session_draft_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_draft_training_session_id ON public.training_session_draft USING btree (training_session_id);


--
-- Name: ix_training_session_draft_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_draft_user_id ON public.training_session_draft USING btree (user_id);


--
-- Name: ix_training_session_exercise_competence_source_competence_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_competence_source_competence_id ON public.training_session_exercise_competence USING btree (source_competence_id);


--
-- Name: ix_training_session_exercise_competence_training_sessio_63c6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_competence_training_sessio_63c6 ON public.training_session_exercise_competence USING btree (training_session_exercise_id);


--
-- Name: ix_training_session_exercise_crew_segment_exercise_session_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_crew_segment_exercise_session_key ON public.training_session_exercise_crew_segment USING btree (exercise_session_key);


--
-- Name: ix_training_session_exercise_crew_segment_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_crew_segment_training_session_id ON public.training_session_exercise_crew_segment USING btree (training_session_id);


--
-- Name: ix_training_session_exercise_element_source_element_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_element_source_element_id ON public.training_session_exercise_element USING btree (source_element_id);


--
-- Name: ix_training_session_exercise_element_source_exercise_element_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_element_source_exercise_element_id ON public.training_session_exercise_element USING btree (source_exercise_element_id);


--
-- Name: ix_training_session_exercise_element_training_session_e_20f0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_element_training_session_e_20f0 ON public.training_session_exercise_element USING btree (training_session_exercise_id);


--
-- Name: ix_training_session_exercise_image_source_exercise_image_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_image_source_exercise_image_id ON public.training_session_exercise_image USING btree (source_exercise_image_id);


--
-- Name: ix_training_session_exercise_image_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_image_storage_key ON public.training_session_exercise_image USING btree (storage_key);


--
-- Name: ix_training_session_exercise_image_training_session_exercise_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_image_training_session_exercise_id ON public.training_session_exercise_image USING btree (training_session_exercise_id);


--
-- Name: ix_training_session_exercise_resolved_for_assessment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_resolved_for_assessment_id ON public.training_session_exercise USING btree (resolved_for_assessment_id);


--
-- Name: ix_training_session_exercise_run_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_run_training_session_id ON public.training_session_exercise_run USING btree (training_session_id);


--
-- Name: ix_training_session_exercise_source_block_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_source_block_id ON public.training_session_exercise USING btree (source_block_id);


--
-- Name: ix_training_session_exercise_source_exercise_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_source_exercise_id ON public.training_session_exercise USING btree (source_exercise_id);


--
-- Name: ix_training_session_exercise_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_training_session_id ON public.training_session_exercise USING btree (training_session_id);


--
-- Name: ix_training_session_exercise_training_session_module_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_exercise_training_session_module_id ON public.training_session_exercise USING btree (training_session_module_id);


--
-- Name: ix_training_session_grading_scheme_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_grading_scheme_id ON public.training_session USING btree (grading_scheme_id);


--
-- Name: ix_training_session_instructor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_instructor_id ON public.training_session USING btree (instructor_id);


--
-- Name: ix_training_session_module_source_module_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_module_source_module_id ON public.training_session_module USING btree (source_module_id);


--
-- Name: ix_training_session_module_source_scenario_day_module_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_module_source_scenario_day_module_id ON public.training_session_module USING btree (source_scenario_day_module_id);


--
-- Name: ix_training_session_module_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_module_training_session_id ON public.training_session_module USING btree (training_session_id);


--
-- Name: ix_training_session_scenario_day_module_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_scenario_day_module_id ON public.training_session USING btree (scenario_day_module_id);


--
-- Name: ix_training_session_scenario_id_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_scenario_id_snapshot ON public.training_session USING btree (scenario_id_snapshot);


--
-- Name: ix_training_session_scenario_pdf_session_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_scenario_pdf_session_order ON public.training_session_scenario_pdf USING btree (training_session_id, order_index);


--
-- Name: ix_training_session_scenario_pdf_source_scenario_pdf_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_scenario_pdf_source_scenario_pdf_id ON public.training_session_scenario_pdf USING btree (source_scenario_pdf_id);


--
-- Name: ix_training_session_scenario_pdf_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_scenario_pdf_storage_key ON public.training_session_scenario_pdf USING btree (storage_key);


--
-- Name: ix_training_session_scenario_pdf_training_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_scenario_pdf_training_session_id ON public.training_session_scenario_pdf USING btree (training_session_id);


--
-- Name: ix_training_session_scenario_revision_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_session_scenario_revision_id ON public.training_session USING btree (scenario_revision_id);


--
-- Name: ix_user_aircraft_aircraft_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_aircraft_aircraft_id ON public.user_aircraft USING btree (aircraft_id);


--
-- Name: ix_user_aircraft_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_aircraft_user_id ON public.user_aircraft USING btree (user_id);


--
-- Name: ix_user_info_date_of_birth; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_info_date_of_birth ON public.user_info USING btree (date_of_birth);


--
-- Name: ix_user_info_photo_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_user_info_photo_storage_key ON public.user_info USING btree (photo_storage_key);


--
-- Name: ix_user_info_position_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_info_position_id ON public.user_info USING btree (position_id);


--
-- Name: ix_user_info_signature_storage_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_user_info_signature_storage_key ON public.user_info USING btree (signature_storage_key);


--
-- Name: ix_user_recurrent_compliance_compliance_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_recurrent_compliance_compliance_id ON public.user_recurrent_compliance USING btree (compliance_id);


--
-- Name: ix_users_public_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_public_id ON public.users USING btree (public_id);


--
-- Name: uq_flight_type_airline_main; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_flight_type_airline_main ON public.flight_type USING btree (airline_id) WHERE is_main;


--
-- Name: uq_grading_scheme_airline_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_grading_scheme_airline_active ON public.grading_scheme USING btree (airline_id) WHERE is_active;


--
-- Name: uq_mistake_report_assessment_client_report; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_mistake_report_assessment_client_report ON public.mistake_report USING btree (assessment_id, client_report_id) WHERE (client_report_id IS NOT NULL);


--
-- Name: uq_training_crew_event_client_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_training_crew_event_client_id ON public.training_session_crew_assignment_event USING btree (training_session_id, client_event_id) WHERE (client_event_id IS NOT NULL);


--
-- Name: uq_training_exercise_run_one_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_training_exercise_run_one_active ON public.training_session_exercise_run USING btree (training_session_id) WHERE ((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'PAUSED'::character varying])::text[]));


--
-- Name: uq_training_exercise_run_one_ready; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_training_exercise_run_one_ready ON public.training_session_exercise_run USING btree (training_session_id, training_session_exercise_id) WHERE ((status)::text = 'READY'::text);


--
-- Name: ai_review ai_review_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_review
    ADD CONSTRAINT ai_review_assessment_id_fkey FOREIGN KEY (assessment_id) REFERENCES public.crew_member_assessment(id) ON DELETE CASCADE;


--
-- Name: ai_review ai_review_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_review
    ADD CONSTRAINT ai_review_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competence(id) ON DELETE CASCADE;


--
-- Name: ai_scenario_approval_token ai_scenario_approval_token_consumed_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_approval_token
    ADD CONSTRAINT ai_scenario_approval_token_consumed_by_user_id_fkey FOREIGN KEY (consumed_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ai_scenario_approval_token ai_scenario_approval_token_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_approval_token
    ADD CONSTRAINT ai_scenario_approval_token_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.ai_scenario_event(id) ON DELETE SET NULL;


--
-- Name: ai_scenario_approval_token ai_scenario_approval_token_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_approval_token
    ADD CONSTRAINT ai_scenario_approval_token_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.ai_scenario_job(id) ON DELETE CASCADE;


--
-- Name: ai_scenario_event ai_scenario_event_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_event
    ADD CONSTRAINT ai_scenario_event_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.ai_scenario_job(id) ON DELETE CASCADE;


--
-- Name: ai_scenario_job ai_scenario_job_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job
    ADD CONSTRAINT ai_scenario_job_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenario(id) ON DELETE SET NULL;


--
-- Name: ai_scenario_job_step ai_scenario_job_step_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job_step
    ADD CONSTRAINT ai_scenario_job_step_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.ai_scenario_job(id) ON DELETE CASCADE;


--
-- Name: ai_scenario_job ai_scenario_job_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_scenario_job
    ADD CONSTRAINT ai_scenario_job_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: aircraft_airline aircraft_airline_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aircraft_airline
    ADD CONSTRAINT aircraft_airline_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: airline_position airline_position_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.airline_position
    ADD CONSTRAINT airline_position_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: auth_sessions auth_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: block_folder block_folder_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder
    ADD CONSTRAINT block_folder_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: block_folder_item block_folder_item_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder_item
    ADD CONSTRAINT block_folder_item_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.element_block(id) ON DELETE CASCADE;


--
-- Name: block_folder_item block_folder_item_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder_item
    ADD CONSTRAINT block_folder_item_folder_id_fkey FOREIGN KEY (folder_id) REFERENCES public.block_folder(id) ON DELETE CASCADE;


--
-- Name: block_folder block_folder_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder
    ADD CONSTRAINT block_folder_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.block_folder(id) ON DELETE SET NULL;


--
-- Name: crew_member_assessment crew_member_assessment_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_member_assessment
    ADD CONSTRAINT crew_member_assessment_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: crew_member_assessment crew_member_assessment_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crew_member_assessment
    ADD CONSTRAINT crew_member_assessment_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: element_block_competence element_block_competence_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_competence
    ADD CONSTRAINT element_block_competence_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.element_block(id) ON DELETE CASCADE;


--
-- Name: element_block_competence element_block_competence_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_competence
    ADD CONSTRAINT element_block_competence_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competence(id) ON DELETE CASCADE;


--
-- Name: element_block_element element_block_element_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_element
    ADD CONSTRAINT element_block_element_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.element_block(id) ON DELETE CASCADE;


--
-- Name: element_block element_block_element_block_param_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block
    ADD CONSTRAINT element_block_element_block_param_id_fkey FOREIGN KEY (element_block_param_id) REFERENCES public.element_block_param(id) ON DELETE SET NULL;


--
-- Name: element_block_element element_block_element_element_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_element
    ADD CONSTRAINT element_block_element_element_id_fkey FOREIGN KEY (element_id) REFERENCES public.element(id) ON DELETE CASCADE;


--
-- Name: element_block_param element_block_param_destination_tl_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_param
    ADD CONSTRAINT element_block_param_destination_tl_id_fkey FOREIGN KEY (destination_tl_id) REFERENCES public.take_off_landing_param(id) ON DELETE SET NULL;


--
-- Name: element_block_param element_block_param_original_tl_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block_param
    ADD CONSTRAINT element_block_param_original_tl_id_fkey FOREIGN KEY (original_tl_id) REFERENCES public.take_off_landing_param(id) ON DELETE SET NULL;


--
-- Name: element_folder element_folder_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder
    ADD CONSTRAINT element_folder_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: element_folder_item element_folder_item_element_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder_item
    ADD CONSTRAINT element_folder_item_element_id_fkey FOREIGN KEY (element_id) REFERENCES public.element(id) ON DELETE CASCADE;


--
-- Name: element_folder_item element_folder_item_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder_item
    ADD CONSTRAINT element_folder_item_folder_id_fkey FOREIGN KEY (folder_id) REFERENCES public.element_folder(id) ON DELETE CASCADE;


--
-- Name: element_folder element_folder_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder
    ADD CONSTRAINT element_folder_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.element_folder(id) ON DELETE SET NULL;


--
-- Name: exercise_competence exercise_competence_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_competence
    ADD CONSTRAINT exercise_competence_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competence(id) ON DELETE CASCADE;


--
-- Name: exercise_competence exercise_competence_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_competence
    ADD CONSTRAINT exercise_competence_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercise(id) ON DELETE CASCADE;


--
-- Name: exercise_element exercise_element_element_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_element
    ADD CONSTRAINT exercise_element_element_id_fkey FOREIGN KEY (element_id) REFERENCES public.element(id) ON DELETE CASCADE;


--
-- Name: exercise_element exercise_element_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_element
    ADD CONSTRAINT exercise_element_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercise(id) ON DELETE CASCADE;


--
-- Name: exercise exercise_exercise_param_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise
    ADD CONSTRAINT exercise_exercise_param_id_fkey FOREIGN KEY (exercise_param_id) REFERENCES public.exercise_param(id) ON DELETE SET NULL;


--
-- Name: exercise_image exercise_image_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_image
    ADD CONSTRAINT exercise_image_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercise(id) ON DELETE CASCADE;


--
-- Name: exercise exercise_module_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise
    ADD CONSTRAINT exercise_module_id_fkey FOREIGN KEY (module_id) REFERENCES public.module(id) ON DELETE CASCADE;


--
-- Name: exercise_param exercise_param_destination_tl_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_param
    ADD CONSTRAINT exercise_param_destination_tl_id_fkey FOREIGN KEY (destination_tl_id) REFERENCES public.take_off_landing_param(id) ON DELETE SET NULL;


--
-- Name: exercise_param exercise_param_original_tl_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exercise_param
    ADD CONSTRAINT exercise_param_original_tl_id_fkey FOREIGN KEY (original_tl_id) REFERENCES public.take_off_landing_param(id) ON DELETE SET NULL;


--
-- Name: feedback_attachment feedback_attachment_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_attachment
    ADD CONSTRAINT feedback_attachment_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.feedback_ticket(id) ON DELETE CASCADE;


--
-- Name: feedback_ticket feedback_ticket_admin_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_ticket
    ADD CONSTRAINT feedback_ticket_admin_user_id_fkey FOREIGN KEY (admin_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: feedback_ticket feedback_ticket_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_ticket
    ADD CONSTRAINT feedback_ticket_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: final_report final_report_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.final_report
    ADD CONSTRAINT final_report_assessment_id_fkey FOREIGN KEY (assessment_id) REFERENCES public.crew_member_assessment(id) ON DELETE CASCADE;


--
-- Name: final_report final_report_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.final_report
    ADD CONSTRAINT final_report_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competence(id) ON DELETE CASCADE;


--
-- Name: behavioural_indicator fk_behavioural_indicator_competence_id_competence; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.behavioural_indicator
    ADD CONSTRAINT fk_behavioural_indicator_competence_id_competence FOREIGN KEY (competence_id) REFERENCES public.competence(id) ON DELETE CASCADE;


--
-- Name: block_folder fk_block_folder_aircraft_id_aircraft_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder
    ADD CONSTRAINT fk_block_folder_aircraft_id_aircraft_airline FOREIGN KEY (aircraft_id) REFERENCES public.aircraft_airline(id) ON DELETE CASCADE;


--
-- Name: block_folder fk_block_folder_archived_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.block_folder
    ADD CONSTRAINT fk_block_folder_archived_by_users FOREIGN KEY (archived_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: competence fk_competence_airline_id_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competence
    ADD CONSTRAINT fk_competence_airline_id_airline FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: element fk_element_aircraft_id_aircraft_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element
    ADD CONSTRAINT fk_element_aircraft_id_aircraft_airline FOREIGN KEY (aircraft_id) REFERENCES public.aircraft_airline(id) ON DELETE CASCADE;


--
-- Name: element fk_element_airline_id_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element
    ADD CONSTRAINT fk_element_airline_id_airline FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: element fk_element_archived_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element
    ADD CONSTRAINT fk_element_archived_by_users FOREIGN KEY (archived_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: element_block fk_element_block_airline_id_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block
    ADD CONSTRAINT fk_element_block_airline_id_airline FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: element_block fk_element_block_archived_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_block
    ADD CONSTRAINT fk_element_block_archived_by_users FOREIGN KEY (archived_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: element_folder fk_element_folder_aircraft_id_aircraft_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder
    ADD CONSTRAINT fk_element_folder_aircraft_id_aircraft_airline FOREIGN KEY (aircraft_id) REFERENCES public.aircraft_airline(id) ON DELETE CASCADE;


--
-- Name: element_folder fk_element_folder_archived_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_folder
    ADD CONSTRAINT fk_element_folder_archived_by_users FOREIGN KEY (archived_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: final_report fk_final_report_grading_scale_value_id_grading_scale_value; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.final_report
    ADD CONSTRAINT fk_final_report_grading_scale_value_id_grading_scale_value FOREIGN KEY (grading_scale_value_id) REFERENCES public.grading_scale_value(id) ON DELETE SET NULL;


--
-- Name: mistake_report fk_mistake_report_assignment_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mistake_report
    ADD CONSTRAINT fk_mistake_report_assignment_event FOREIGN KEY (assignment_event_id_at_observation) REFERENCES public.training_session_crew_assignment_event(id) ON DELETE SET NULL;


--
-- Name: mistake_report fk_mistake_report_training_session_exercise_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mistake_report
    ADD CONSTRAINT fk_mistake_report_training_session_exercise_id FOREIGN KEY (training_session_exercise_id) REFERENCES public.training_session_exercise(id) ON DELETE RESTRICT;


--
-- Name: scenario fk_scenario_aircraft_id_aircraft_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario
    ADD CONSTRAINT fk_scenario_aircraft_id_aircraft_airline FOREIGN KEY (aircraft_id) REFERENCES public.aircraft_airline(id) ON DELETE CASCADE;


--
-- Name: scenario fk_scenario_archived_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario
    ADD CONSTRAINT fk_scenario_archived_by_users FOREIGN KEY (archived_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scenario_content_set fk_scenario_content_set_aircraft_id_aircraft_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set
    ADD CONSTRAINT fk_scenario_content_set_aircraft_id_aircraft_airline FOREIGN KEY (aircraft_id) REFERENCES public.aircraft_airline(id) ON DELETE CASCADE;


--
-- Name: scenario fk_scenario_deleted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario
    ADD CONSTRAINT fk_scenario_deleted_by_users FOREIGN KEY (deleted_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scenario_revision fk_scenario_revision_parent_revision_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_revision
    ADD CONSTRAINT fk_scenario_revision_parent_revision_id FOREIGN KEY (parent_revision_id) REFERENCES public.scenario_revision(id) ON DELETE SET NULL;


--
-- Name: speech_session fk_speech_session_training_session_id_training_session; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session
    ADD CONSTRAINT fk_speech_session_training_session_id_training_session FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE SET NULL;


--
-- Name: training_session_crew_assignment_event fk_training_crew_event_cm1_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT fk_training_crew_event_cm1_assessment FOREIGN KEY (training_session_id, cm1_assessment_id_after) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE RESTRICT;


--
-- Name: training_session_crew_assignment_event fk_training_crew_event_cm2_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT fk_training_crew_event_cm2_assessment FOREIGN KEY (training_session_id, cm2_assessment_id_after) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE RESTRICT;


--
-- Name: training_session_crew_assignment_event fk_training_crew_event_exercise; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT fk_training_crew_event_exercise FOREIGN KEY (training_session_id, training_session_exercise_id) REFERENCES public.training_session_exercise(training_session_id, id) ON DELETE RESTRICT;


--
-- Name: training_session_crew_assignment_event fk_training_crew_event_previous; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT fk_training_crew_event_previous FOREIGN KEY (training_session_id, previous_event_public_id) REFERENCES public.training_session_crew_assignment_event(training_session_id, public_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: training_session_crew_assignment_event fk_training_crew_event_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT fk_training_crew_event_run FOREIGN KEY (training_session_id, exercise_session_key, training_session_exercise_id) REFERENCES public.training_session_exercise_run(training_session_id, exercise_session_key, training_session_exercise_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: training_session_exercise_crew_segment fk_training_crew_segment_cm1_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT fk_training_crew_segment_cm1_assessment FOREIGN KEY (training_session_id, cm1_assessment_id) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_crew_segment fk_training_crew_segment_cm2_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT fk_training_crew_segment_cm2_assessment FOREIGN KEY (training_session_id, cm2_assessment_id) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_crew_segment fk_training_crew_segment_exercise; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT fk_training_crew_segment_exercise FOREIGN KEY (training_session_id, training_session_exercise_id) REFERENCES public.training_session_exercise(training_session_id, id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_crew_segment fk_training_crew_segment_pf_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT fk_training_crew_segment_pf_assessment FOREIGN KEY (training_session_id, pf_assessment_id) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_crew_segment fk_training_crew_segment_pm_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT fk_training_crew_segment_pm_assessment FOREIGN KEY (training_session_id, pm_assessment_id) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_crew_segment fk_training_crew_segment_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT fk_training_crew_segment_run FOREIGN KEY (training_session_id, exercise_session_key, training_session_exercise_id) REFERENCES public.training_session_exercise_run(training_session_id, exercise_session_key, training_session_exercise_id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_crew_segment fk_training_crew_segment_start_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT fk_training_crew_segment_start_event FOREIGN KEY (training_session_id, starts_after_event_public_id) REFERENCES public.training_session_crew_assignment_event(training_session_id, public_id) ON DELETE RESTRICT;


--
-- Name: training_session_crew_state fk_training_crew_state_cm1_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_state
    ADD CONSTRAINT fk_training_crew_state_cm1_assessment FOREIGN KEY (training_session_id, current_cm1_assessment_id) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE RESTRICT;


--
-- Name: training_session_crew_state fk_training_crew_state_cm2_assessment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_state
    ADD CONSTRAINT fk_training_crew_state_cm2_assessment FOREIGN KEY (training_session_id, current_cm2_assessment_id) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE RESTRICT;


--
-- Name: training_session_crew_state fk_training_crew_state_current_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_state
    ADD CONSTRAINT fk_training_crew_state_current_event FOREIGN KEY (training_session_id, current_event_public_id) REFERENCES public.training_session_crew_assignment_event(training_session_id, public_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: training_session_exercise fk_training_exercise_resolved_assessment_training; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise
    ADD CONSTRAINT fk_training_exercise_resolved_assessment_training FOREIGN KEY (training_session_id, resolved_for_assessment_id) REFERENCES public.crew_member_assessment(training_session_id, id) ON DELETE RESTRICT;


--
-- Name: training_session_exercise_run fk_training_exercise_run_exercise; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_run
    ADD CONSTRAINT fk_training_exercise_run_exercise FOREIGN KEY (training_session_id, training_session_exercise_id, runtime_exercise_id) REFERENCES public.training_session_exercise(training_session_id, id, runtime_exercise_id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_run fk_training_exercise_run_initial_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_run
    ADD CONSTRAINT fk_training_exercise_run_initial_event FOREIGN KEY (training_session_id, initial_assignment_event_public_id) REFERENCES public.training_session_crew_assignment_event(training_session_id, public_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: training_session fk_training_session_grading_scheme_id_grading_scheme; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session
    ADD CONSTRAINT fk_training_session_grading_scheme_id_grading_scheme FOREIGN KEY (grading_scheme_id) REFERENCES public.grading_scheme(id) ON DELETE RESTRICT;


--
-- Name: training_session fk_training_session_scenario_revision_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session
    ADD CONSTRAINT fk_training_session_scenario_revision_id FOREIGN KEY (scenario_revision_id) REFERENCES public.scenario_revision(id) ON DELETE RESTRICT;


--
-- Name: user_aircraft fk_user_aircraft_aircraft_id_aircraft_airline; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_aircraft
    ADD CONSTRAINT fk_user_aircraft_aircraft_id_aircraft_airline FOREIGN KEY (aircraft_id) REFERENCES public.aircraft_airline(id) ON DELETE CASCADE;


--
-- Name: user_info fk_user_info_position_id_airline_position; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_info
    ADD CONSTRAINT fk_user_info_position_id_airline_position FOREIGN KEY (position_id) REFERENCES public.airline_position(id) ON DELETE SET NULL;


--
-- Name: flight_type flight_type_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type
    ADD CONSTRAINT flight_type_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: flight_type_competence_threshold flight_type_competence_threshold_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type_competence_threshold
    ADD CONSTRAINT flight_type_competence_threshold_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competence(id) ON DELETE CASCADE;


--
-- Name: flight_type_competence_threshold flight_type_competence_threshold_flight_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flight_type_competence_threshold
    ADD CONSTRAINT flight_type_competence_threshold_flight_type_id_fkey FOREIGN KEY (flight_type_id) REFERENCES public.flight_type(id) ON DELETE CASCADE;


--
-- Name: grading_scale_value grading_scale_value_grading_scheme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scale_value
    ADD CONSTRAINT grading_scale_value_grading_scheme_id_fkey FOREIGN KEY (grading_scheme_id) REFERENCES public.grading_scheme(id) ON DELETE CASCADE;


--
-- Name: grading_scheme grading_scheme_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_scheme
    ADD CONSTRAINT grading_scheme_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: mistake_report mistake_report_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mistake_report
    ADD CONSTRAINT mistake_report_assessment_id_fkey FOREIGN KEY (assessment_id) REFERENCES public.crew_member_assessment(id) ON DELETE CASCADE;


--
-- Name: mistake_report mistake_report_behavioural_indicator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mistake_report
    ADD CONSTRAINT mistake_report_behavioural_indicator_id_fkey FOREIGN KEY (behavioural_indicator_id) REFERENCES public.behavioural_indicator(id) ON DELETE SET NULL;


--
-- Name: mistake_report mistake_report_competence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mistake_report
    ADD CONSTRAINT mistake_report_competence_id_fkey FOREIGN KEY (competence_id) REFERENCES public.competence(id) ON DELETE SET NULL;


--
-- Name: module module_content_subcolumn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module
    ADD CONSTRAINT module_content_subcolumn_id_fkey FOREIGN KEY (content_subcolumn_id) REFERENCES public.scenario_content_subcolumn(id) ON DELETE SET NULL;


--
-- Name: module module_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.module
    ADD CONSTRAINT module_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenario(id) ON DELETE CASCADE;


--
-- Name: role_privileges role_privileges_privilege_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_privileges
    ADD CONSTRAINT role_privileges_privilege_id_fkey FOREIGN KEY (privilege_id) REFERENCES public.privileges(id) ON DELETE CASCADE;


--
-- Name: role_privileges role_privileges_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_privileges
    ADD CONSTRAINT role_privileges_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: scenario scenario_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario
    ADD CONSTRAINT scenario_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: scenario_content_cell scenario_content_cell_content_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_cell
    ADD CONSTRAINT scenario_content_cell_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.scenario_content_set(id) ON DELETE CASCADE;


--
-- Name: scenario_content_cell scenario_content_cell_requirement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_cell
    ADD CONSTRAINT scenario_content_cell_requirement_id_fkey FOREIGN KEY (requirement_id) REFERENCES public.scenario_content_requirement(id) ON DELETE CASCADE;


--
-- Name: scenario_content_cell scenario_content_cell_set_label_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_cell
    ADD CONSTRAINT scenario_content_cell_set_label_id_fkey FOREIGN KEY (set_label_id) REFERENCES public.scenario_content_set_label(id) ON DELETE CASCADE;


--
-- Name: scenario_content_cell scenario_content_cell_subcolumn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_cell
    ADD CONSTRAINT scenario_content_cell_subcolumn_id_fkey FOREIGN KEY (subcolumn_id) REFERENCES public.scenario_content_subcolumn(id) ON DELETE CASCADE;


--
-- Name: scenario_content_folder scenario_content_folder_content_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_folder
    ADD CONSTRAINT scenario_content_folder_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.scenario_content_set(id) ON DELETE CASCADE;


--
-- Name: scenario_content_folder scenario_content_folder_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_folder
    ADD CONSTRAINT scenario_content_folder_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.scenario_content_folder(id) ON DELETE CASCADE;


--
-- Name: scenario_content_requirement scenario_content_requirement_content_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement
    ADD CONSTRAINT scenario_content_requirement_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.scenario_content_set(id) ON DELETE CASCADE;


--
-- Name: scenario_content_requirement_element scenario_content_requirement_element_element_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement_element
    ADD CONSTRAINT scenario_content_requirement_element_element_id_fkey FOREIGN KEY (element_id) REFERENCES public.element(id) ON DELETE CASCADE;


--
-- Name: scenario_content_requirement_element scenario_content_requirement_element_requirement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement_element
    ADD CONSTRAINT scenario_content_requirement_element_requirement_id_fkey FOREIGN KEY (requirement_id) REFERENCES public.scenario_content_requirement(id) ON DELETE CASCADE;


--
-- Name: scenario_content_requirement scenario_content_requirement_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_requirement
    ADD CONSTRAINT scenario_content_requirement_folder_id_fkey FOREIGN KEY (folder_id) REFERENCES public.scenario_content_folder(id) ON DELETE CASCADE;


--
-- Name: scenario_content_set scenario_content_set_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set
    ADD CONSTRAINT scenario_content_set_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE CASCADE;


--
-- Name: scenario_content_set scenario_content_set_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set
    ADD CONSTRAINT scenario_content_set_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scenario_content_set_label scenario_content_set_label_content_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label
    ADD CONSTRAINT scenario_content_set_label_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.scenario_content_set(id) ON DELETE CASCADE;


--
-- Name: scenario_content_set_label_scenario scenario_content_set_label_scenario_label_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label_scenario
    ADD CONSTRAINT scenario_content_set_label_scenario_label_id_fkey FOREIGN KEY (label_id) REFERENCES public.scenario_content_set_label(id) ON DELETE CASCADE;


--
-- Name: scenario_content_set_label_scenario scenario_content_set_label_scenario_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set_label_scenario
    ADD CONSTRAINT scenario_content_set_label_scenario_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenario(id) ON DELETE CASCADE;


--
-- Name: scenario_content_set scenario_content_set_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_set
    ADD CONSTRAINT scenario_content_set_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scenario_content_subcolumn scenario_content_subcolumn_content_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_content_subcolumn
    ADD CONSTRAINT scenario_content_subcolumn_content_set_id_fkey FOREIGN KEY (content_set_id) REFERENCES public.scenario_content_set(id) ON DELETE CASCADE;


--
-- Name: scenario scenario_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario
    ADD CONSTRAINT scenario_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scenario_day_module scenario_day_module_module_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_day_module
    ADD CONSTRAINT scenario_day_module_module_id_fkey FOREIGN KEY (module_id) REFERENCES public.module(id) ON DELETE CASCADE;


--
-- Name: scenario_day_module scenario_day_module_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_day_module
    ADD CONSTRAINT scenario_day_module_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenario(id) ON DELETE CASCADE;


--
-- Name: scenario_edit_lock scenario_edit_lock_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_edit_lock
    ADD CONSTRAINT scenario_edit_lock_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenario(id) ON DELETE CASCADE;


--
-- Name: scenario_edit_lock scenario_edit_lock_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_edit_lock
    ADD CONSTRAINT scenario_edit_lock_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scenario_pdf scenario_pdf_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_pdf
    ADD CONSTRAINT scenario_pdf_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenario(id) ON DELETE CASCADE;


--
-- Name: scenario_revision scenario_revision_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_revision
    ADD CONSTRAINT scenario_revision_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scenario_revision scenario_revision_scenario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_revision
    ADD CONSTRAINT scenario_revision_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES public.scenario(id) ON DELETE CASCADE;


--
-- Name: scenario scenario_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario
    ADD CONSTRAINT scenario_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: speech_artifact speech_artifact_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_artifact
    ADD CONSTRAINT speech_artifact_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.speech_session(id) ON DELETE CASCADE;


--
-- Name: speech_diarization_block speech_diarization_block_block_wav_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_diarization_block
    ADD CONSTRAINT speech_diarization_block_block_wav_artifact_id_fkey FOREIGN KEY (block_wav_artifact_id) REFERENCES public.speech_artifact(id) ON DELETE SET NULL;


--
-- Name: speech_diarization_block speech_diarization_block_diarization_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_diarization_block
    ADD CONSTRAINT speech_diarization_block_diarization_artifact_id_fkey FOREIGN KEY (diarization_artifact_id) REFERENCES public.speech_artifact(id) ON DELETE SET NULL;


--
-- Name: speech_diarization_block speech_diarization_block_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_diarization_block
    ADD CONSTRAINT speech_diarization_block_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.speech_session(id) ON DELETE CASCADE;


--
-- Name: speech_external_job speech_external_job_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_external_job
    ADD CONSTRAINT speech_external_job_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.speech_session(id) ON DELETE CASCADE;


--
-- Name: speech_review speech_review_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_review
    ADD CONSTRAINT speech_review_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.speech_session(id) ON DELETE CASCADE;


--
-- Name: speech_session_chunk speech_session_chunk_asr_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session_chunk
    ADD CONSTRAINT speech_session_chunk_asr_artifact_id_fkey FOREIGN KEY (asr_artifact_id) REFERENCES public.speech_artifact(id) ON DELETE SET NULL;


--
-- Name: speech_session_chunk speech_session_chunk_raw_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session_chunk
    ADD CONSTRAINT speech_session_chunk_raw_artifact_id_fkey FOREIGN KEY (raw_artifact_id) REFERENCES public.speech_artifact(id) ON DELETE SET NULL;


--
-- Name: speech_session_chunk speech_session_chunk_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session_chunk
    ADD CONSTRAINT speech_session_chunk_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.speech_session(id) ON DELETE CASCADE;


--
-- Name: speech_session_chunk speech_session_chunk_wav_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session_chunk
    ADD CONSTRAINT speech_session_chunk_wav_artifact_id_fkey FOREIGN KEY (wav_artifact_id) REFERENCES public.speech_artifact(id) ON DELETE SET NULL;


--
-- Name: speech_session speech_session_transcript_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session
    ADD CONSTRAINT speech_session_transcript_artifact_id_fkey FOREIGN KEY (transcript_artifact_id) REFERENCES public.speech_artifact(id) ON DELETE SET NULL;


--
-- Name: speech_session speech_session_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_session
    ADD CONSTRAINT speech_session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: speech_speaker_profile speech_speaker_profile_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_speaker_profile
    ADD CONSTRAINT speech_speaker_profile_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.speech_session(id) ON DELETE CASCADE;


--
-- Name: speech_transcript_segment speech_transcript_segment_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.speech_transcript_segment
    ADD CONSTRAINT speech_transcript_segment_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.speech_session(id) ON DELETE CASCADE;


--
-- Name: takeoff_param_details takeoff_param_details_take_off_landing_param_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.takeoff_param_details
    ADD CONSTRAINT takeoff_param_details_take_off_landing_param_id_fkey FOREIGN KEY (take_off_landing_param_id) REFERENCES public.take_off_landing_param(id) ON DELETE CASCADE;


--
-- Name: training_session_crew_assignment_event training_session_crew_assignment_event_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT training_session_crew_assignment_event_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: training_session_crew_assignment_event training_session_crew_assignment_event_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_assignment_event
    ADD CONSTRAINT training_session_crew_assignment_event_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: training_session_crew_state training_session_crew_state_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_crew_state
    ADD CONSTRAINT training_session_crew_state_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: training_session_draft training_session_draft_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_draft
    ADD CONSTRAINT training_session_draft_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: training_session_draft training_session_draft_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_draft
    ADD CONSTRAINT training_session_draft_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_competence training_session_exercise_com_training_session_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_competence
    ADD CONSTRAINT training_session_exercise_com_training_session_exercise_id_fkey FOREIGN KEY (training_session_exercise_id) REFERENCES public.training_session_exercise(id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_crew_segment training_session_exercise_crew_segment_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_crew_segment
    ADD CONSTRAINT training_session_exercise_crew_segment_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_element training_session_exercise_ele_training_session_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_element
    ADD CONSTRAINT training_session_exercise_ele_training_session_exercise_id_fkey FOREIGN KEY (training_session_exercise_id) REFERENCES public.training_session_exercise(id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_image training_session_exercise_ima_training_session_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_image
    ADD CONSTRAINT training_session_exercise_ima_training_session_exercise_id_fkey FOREIGN KEY (training_session_exercise_id) REFERENCES public.training_session_exercise(id) ON DELETE CASCADE;


--
-- Name: training_session_exercise_run training_session_exercise_run_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise_run
    ADD CONSTRAINT training_session_exercise_run_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: training_session_exercise training_session_exercise_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise
    ADD CONSTRAINT training_session_exercise_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: training_session_exercise training_session_exercise_training_session_module_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_exercise
    ADD CONSTRAINT training_session_exercise_training_session_module_id_fkey FOREIGN KEY (training_session_module_id) REFERENCES public.training_session_module(id) ON DELETE CASCADE;


--
-- Name: training_session training_session_instructor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session
    ADD CONSTRAINT training_session_instructor_id_fkey FOREIGN KEY (instructor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: training_session_module training_session_module_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_module
    ADD CONSTRAINT training_session_module_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: training_session training_session_scenario_day_module_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session
    ADD CONSTRAINT training_session_scenario_day_module_id_fkey FOREIGN KEY (scenario_day_module_id) REFERENCES public.scenario_day_module(id) ON DELETE SET NULL;


--
-- Name: training_session_scenario_pdf training_session_scenario_pdf_training_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session_scenario_pdf
    ADD CONSTRAINT training_session_scenario_pdf_training_session_id_fkey FOREIGN KEY (training_session_id) REFERENCES public.training_session(id) ON DELETE CASCADE;


--
-- Name: user_aircraft user_aircraft_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_aircraft
    ADD CONSTRAINT user_aircraft_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_info user_info_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_info
    ADD CONSTRAINT user_info_id_fkey FOREIGN KEY (id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_recurrent_compliance user_recurrent_compliance_compliance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recurrent_compliance
    ADD CONSTRAINT user_recurrent_compliance_compliance_id_fkey FOREIGN KEY (compliance_id) REFERENCES public.scenario_content_set(id) ON DELETE CASCADE;


--
-- Name: user_recurrent_compliance user_recurrent_compliance_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recurrent_compliance
    ADD CONSTRAINT user_recurrent_compliance_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_airline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_airline_id_fkey FOREIGN KEY (airline_id) REFERENCES public.airline(id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict U5BTBxJcadSDHMbsbmb9fFaKRD99Et2nYh55P0dSATvyLcC8apv5Fj8Wv1cBCoQ

