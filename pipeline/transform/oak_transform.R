#!/usr/bin/env Rscript
# sdtm.oak transformation: raw EDC-style extracts -> SDTM VS and DM.
#
# Input: a directory of raw CSVs the wrapper flattens out of the broker
# (raw_vitals.csv, raw_dm.csv). Output: SDTM domain CSVs (vs.csv, dm.csv)
# the wrapper then wraps as Dataset-JSON. The mapping logic is sdtm.oak,
# the open-source CDISC/pharmaverse SDTM engine, used as intended:
# controlled-terminology assignment, direct assignment, and sequence
# derivation over oak id variables.

suppressPackageStartupMessages({
  library(sdtm.oak)
  library(dplyr)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("usage: oak_transform.R <raw_dir> <out_dir> <studyid>")
}
raw_dir <- args[1]
out_dir <- args[2]
studyid <- args[3]
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

# Study controlled terminology, sdtm.oak ct_spec shape. Collected values
# come from the EDC extract; term values are SDTM submission values.
study_ct <- tibble::tribble(
  ~codelist_code, ~collected_value, ~term_synonyms,             ~term_value,
  "C66741",       "SYSBP",          "Systolic BP",              "SYSBP",
  "C66741",       "DIABP",          "Diastolic BP",             "DIABP",
  "C66741",       "HR",             "Heart Rate;Pulse",         "PULSE",
  "C67153",       "SYSBP",          NA,                         "Systolic Blood Pressure",
  "C67153",       "DIABP",          NA,                         "Diastolic Blood Pressure",
  "C67153",       "HR",             NA,                         "Pulse Rate",
  "C66770",       "mmHg",           NA,                         "mmHg",
  "C66770",       "beats/min",      "bpm",                      "beats/min",
  "C66731",       "M",              "Male",                     "M",
  "C66731",       "F",              "Female",                   "F",
  "C66731",       "MALE",           NA,                         "M",
  "C66731",       "FEMALE",         NA,                         "F"
)

## ---- VS: vital signs ----------------------------------------------------

vitals_raw <- read.csv(file.path(raw_dir, "raw_vitals.csv"),
                       stringsAsFactors = FALSE, colClasses = "character")

if (nrow(vitals_raw) > 0) {
  vitals_raw <- generate_oak_id_vars(vitals_raw,
                                     pat_var = "PATNUM",
                                     raw_src = "edc_vitals")

  vs <- assign_ct(
    raw_dat = vitals_raw,
    raw_var = "PARAMCD",
    tgt_var = "VSTESTCD",
    ct_spec = study_ct,
    ct_clst = "C66741",
    id_vars = oak_id_vars()
  ) %>%
    assign_ct(
      raw_dat = vitals_raw,
      raw_var = "PARAMCD",
      tgt_var = "VSTEST",
      ct_spec = study_ct,
      ct_clst = "C67153",
      id_vars = oak_id_vars()
    ) %>%
    assign_no_ct(
      raw_dat = vitals_raw,
      raw_var = "VALUE",
      tgt_var = "VSORRES",
      id_vars = oak_id_vars()
    ) %>%
    assign_ct(
      raw_dat = vitals_raw,
      raw_var = "UNIT",
      tgt_var = "VSORRESU",
      ct_spec = study_ct,
      ct_clst = "C66770",
      id_vars = oak_id_vars()
    ) %>%
    # COLLECTED_AT arrives ISO 8601 from the broker's observedAt, so a
    # direct assignment is already conformant for --DTC.
    assign_no_ct(
      raw_dat = vitals_raw,
      raw_var = "COLLECTED_AT",
      tgt_var = "VSDTC",
      id_vars = oak_id_vars()
    ) %>%
    assign_no_ct(
      raw_dat = vitals_raw,
      raw_var = "VISIT",
      tgt_var = "VISIT",
      id_vars = oak_id_vars()
    ) %>%
    assign_no_ct(
      raw_dat = vitals_raw,
      raw_var = "VISITNUM",
      tgt_var = "VISITNUM",
      id_vars = oak_id_vars()
    ) %>%
    mutate(
      STUDYID = studyid,
      DOMAIN = "VS",
      USUBJID = paste0(studyid, "-", patient_number),
      VSSTRESC = VSORRES,
      VSSTRESN = suppressWarnings(as.numeric(VSORRES)),
      VSSTRESU = VSORRESU,
      VISITNUM = suppressWarnings(as.numeric(VISITNUM))
    ) %>%
    derive_seq(tgt_var = "VSSEQ",
               rec_vars = c("USUBJID", "VSTESTCD", "VSDTC")) %>%
    select(STUDYID, DOMAIN, USUBJID, VSSEQ, VSTESTCD, VSTEST,
           VSORRES, VSORRESU, VSSTRESC, VSSTRESN, VSSTRESU,
           VISITNUM, VISIT, VSDTC)

  write.csv(vs, file.path(out_dir, "vs.csv"), row.names = FALSE, na = "")
  cat("VS:", nrow(vs), "records\n")
} else {
  cat("VS: no raw vitals, skipped\n")
}

## ---- DM: demographics ---------------------------------------------------

dm_raw <- read.csv(file.path(raw_dir, "raw_dm.csv"),
                   stringsAsFactors = FALSE, colClasses = "character")

if (nrow(dm_raw) > 0) {
  dm_raw <- generate_oak_id_vars(dm_raw,
                                 pat_var = "PATNUM",
                                 raw_src = "edc_dm")

  dm <- assign_no_ct(
    raw_dat = dm_raw,
    raw_var = "PATNUM",
    tgt_var = "SUBJID",
    id_vars = oak_id_vars()
  ) %>%
    assign_ct(
      raw_dat = dm_raw,
      raw_var = "SEX",
      tgt_var = "SEX",
      ct_spec = study_ct,
      ct_clst = "C66731",
      id_vars = oak_id_vars()
    ) %>%
    assign_no_ct(
      raw_dat = dm_raw,
      raw_var = "COUNTRY",
      tgt_var = "COUNTRY",
      id_vars = oak_id_vars()
    ) %>%
    assign_no_ct(
      raw_dat = dm_raw,
      raw_var = "ENROLLDT",
      tgt_var = "RFSTDTC",
      id_vars = oak_id_vars()
    ) %>%
    assign_no_ct(
      raw_dat = dm_raw,
      raw_var = "ARMCD",
      tgt_var = "ARMCD",
      id_vars = oak_id_vars()
    ) %>%
    assign_no_ct(
      raw_dat = dm_raw,
      raw_var = "ARM",
      tgt_var = "ARM",
      id_vars = oak_id_vars()
    ) %>%
    mutate(
      STUDYID = studyid,
      DOMAIN = "DM",
      USUBJID = paste0(studyid, "-", patient_number)
    ) %>%
    select(STUDYID, DOMAIN, USUBJID, SUBJID, RFSTDTC,
           SEX, COUNTRY, ARMCD, ARM)

  write.csv(dm, file.path(out_dir, "dm.csv"), row.names = FALSE, na = "")
  cat("DM:", nrow(dm), "records\n")
} else {
  cat("DM: no raw demographics, skipped\n")
}
