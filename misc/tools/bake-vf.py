"""
This script "bakes" the final Inter variable fonts.

This script performs the following:
  1. Renames the family to "Inter Variable"
  2. Updates style names to scrub away "Display"
  3. Builds a STAT table

How to debug/develop this script:

1. create a working dir and build the initial fonts:

  mkdir -p build/bake
  make -j var

2. after making changes, run script and inspect with ttx:

  ( for a in build/fonts/var/.Inter-*.var.ttf; do
      python misc/tools/bake-vf.py "$a" -o build/bake/"$(basename "${a/.Inter/Inter}")"
    done && ttx -t STAT -i -f -s build/bake/Inter-*.ttf )

"""
import sys, os, os.path, re, argparse
from fontTools.ttLib import TTFont
from fontTools.otlLib.builder import buildStatTable


# stat_axes_format_2 is used for making a STAT table with format 1 & 2 records
def stat_axes_format_2(is_italic):
  return [
    { "name": "Optical Size", "tag": "opsz", "ordering": 0, "values": [
      dict(nominalValue=14, rangeMinValue=14, rangeMaxValue=21, name="14pt"),
      dict(nominalValue=28, rangeMinValue=21, rangeMaxValue=28, name="28pt"),
    ] },
    { "name": "Weight", "tag": "wght", "ordering": 1, "values": [
      dict(nominalValue=100, rangeMinValue=100, rangeMaxValue=150, name="Thin"),
      dict(nominalValue=200, rangeMinValue=150, rangeMaxValue=250, name="ExtraLight"),
      dict(nominalValue=300, rangeMinValue=250, rangeMaxValue=350, name="Light"),
      dict(nominalValue=400, rangeMinValue=350, rangeMaxValue=450, name="Regular",
           flags=0x2, linkedValue=660),
      dict(nominalValue=500, rangeMinValue=450, rangeMaxValue=540, name="Medium"),
      dict(nominalValue=580, rangeMinValue=540, rangeMaxValue=620, name="SemiBold"),
      dict(nominalValue=660, rangeMinValue=620, rangeMaxValue=720, name="Bold"),
      dict(nominalValue=780, rangeMinValue=720, rangeMaxValue=840, name="ExtraBold"),
      dict(nominalValue=900, rangeMinValue=840, rangeMaxValue=900, name="Black"),
    ] },
    { "name": "Italic", "tag": "ital", "ordering": 2, "values": [
        dict(value=1, name="Italic") if is_italic else \
        dict(value=0, name="Roman", flags=0x2, linkedValue=1),
    ] },
  ]


# stat_axes_format_3 is used for making a STAT table with format 1 & 3 records
def stat_axes_format_3(is_italic):
  # see https://learn.microsoft.com/en-us/typography/opentype/spec/
  #     stat#axis-value-table-format-3
  suffix = " Italic" if is_italic else ""
  return [
    { "name": "Optical Size", "tag": "opsz" },
    { "name": "Weight", "tag": "wght", "values": [
      { "name": "Thin"+suffix,       "value": 100, "linkedValue": 400 },
      { "name": "ExtraLight"+suffix, "value": 200, "linkedValue": 500 },
      { "name": "Light"+suffix,      "value": 300, "linkedValue": 580 },
      { "name": "Regular"+suffix,    "value": 400, "linkedValue": 660, "flags":0x2 },
      { "name": "Medium"+suffix,     "value": 500, "linkedValue": 780 },
      { "name": "SemiBold"+suffix,   "value": 580, "linkedValue": 900 },
      { "name": "Bold"+suffix,       "value": 660 },
      { "name": "ExtraBold"+suffix,  "value": 780 },
      { "name": "Black"+suffix,      "value": 900 },
    ]},
  ]


# STAT_AXES is used for making a STAT table with format 4 records
STAT_AXES = [
  { "name": "Optical Size", "tag": "opsz" },
  { "name": "Weight",       "tag": "wght" },
  { "name": "Italic",       "tag": "ital" }
]

# stat_locations is used for making a STAT table with format 4 records
def stat_locations(is_italic):
  # see https://learn.microsoft.com/en-us/typography/opentype/spec/
  #     stat#axis-value-table-format-4
  ital = 1 if is_italic else 0
  suffix = " Italic" if is_italic else ""
  return [
    { "name": "Thin"+suffix,       "location":{"wght":100, "ital":ital} },
    { "name": "ExtraLight"+suffix, "location":{"wght":200, "ital":ital} },
    { "name": "Light"+suffix,      "location":{"wght":300, "ital":ital} },
    { "name": "Regular"+suffix,    "location":{"wght":400, "ital":ital}, "flags":0x2 },
    { "name": "Medium"+suffix,     "location":{"wght":500, "ital":ital} },
    { "name": "SemiBold"+suffix,   "location":{"wght":580, "ital":ital} },
    { "name": "Bold"+suffix,       "location":{"wght":660, "ital":ital} },
    { "name": "ExtraBold"+suffix,  "location":{"wght":780, "ital":ital} },
    { "name": "Black"+suffix,      "location":{"wght":900, "ital":ital} },
  ]


WINDOWS_ENGLISH_IDS = 3, 1, 0x409
MAC_ROMAN_IDS = 1, 0, 0

LEGACY_FAMILY       = 1
SUBFAMILY_NAME      = 2
TRUETYPE_UNIQUE_ID  = 3
FULL_NAME           = 4
POSTSCRIPT_NAME     = 6
PREFERRED_FAMILY    = 16
TYPO_SUBFAMILY_NAME = 17
WWS_FAMILY          = 21
VAR_PS_NAME_PREFIX  = 25


FAMILY_RELATED_IDS = set([
  LEGACY_FAMILY,
  TRUETYPE_UNIQUE_ID,
  FULL_NAME,
  POSTSCRIPT_NAME,
  PREFERRED_FAMILY,
  WWS_FAMILY,
  VAR_PS_NAME_PREFIX,
])

WHITESPACE_RE = re.compile(r'\s+')


def remove_whitespace(s):
  return WHITESPACE_RE.sub('', s)


def normalize_whitespace(s):
  return WHITESPACE_RE.sub(' ', s)


def remove_substring(s, substr):
  # examples of remove_substring(s, "Display"):
  #   "Inter Display"   => "Inter"
  #   "Display Lol"     => "Lol"
  #   "Foo Display Lol" => "Foo Lol"
  #   " Foo   Bar Lol " => "Foo Bar Lol"
  return normalize_whitespace(s.strip().replace(substr, '')).strip()


def font_is_italic(ttfont):
  """Check if the font has the word "Italic" in its stylename"""
  stylename = ttfont["name"].getName(2, 3, 1, 0x409).toUnicode()
  return True if "Italic" in stylename else False


def set_full_name(font, fullName, fullNamePs):
  nameTable = font["name"]
  nameTable.setName(fullName, FULL_NAME, 1, 0, 0)     # mac
  nameTable.setName(fullName, FULL_NAME, 3, 1, 0x409) # windows
  nameTable.setName(fullNamePs, POSTSCRIPT_NAME, 1, 0, 0)     # mac
  nameTable.setName(fullNamePs, POSTSCRIPT_NAME, 3, 1, 0x409) # windows


def getFamilyName(font):
  nameTable = font["name"]
  r = None
  for plat_id, enc_id, lang_id in (WINDOWS_ENGLISH_IDS, MAC_ROMAN_IDS):
    for name_id in (PREFERRED_FAMILY, LEGACY_FAMILY):
      r = nameTable.getName(nameID=name_id, platformID=plat_id, platEncID=enc_id, langID=lang_id)
      if r is not None:
        break
    if r is not None:
      break
  if not r:
    raise ValueError("family name not found")
  return r.toUnicode()


def getFamilyNames(font):
  nameTable = font["name"]
  r = None
  names = dict()  # dict in Py >=3.7 maintains insertion order
  for plat_id, enc_id, lang_id in (WINDOWS_ENGLISH_IDS, MAC_ROMAN_IDS):
    for name_id in (PREFERRED_FAMILY, LEGACY_FAMILY):
      r = nameTable.getName(
        nameID=name_id, platformID=plat_id, platEncID=enc_id, langID=lang_id)
      if r:
        names[r.toUnicode()] = True
  if len(names) == 0:
    raise ValueError("family name not found")
  names = list(names.keys())
  names.sort()
  names.reverse() # longest first
  return names


def getStyleName(font):
  nameTable = font["name"]
  for plat_id, enc_id, lang_id in (WINDOWS_ENGLISH_IDS, MAC_ROMAN_IDS):
    for name_id in (TYPO_SUBFAMILY_NAME, SUBFAMILY_NAME):
      r = nameTable.getName(
        nameID=name_id, platformID=plat_id, platEncID=enc_id, langID=lang_id)
      if r is not None:
        return r.toUnicode()
  raise ValueError("style name not found")


def setStyleName(font, newStyleName):
  newFullName = getFamilyName(font).strip()
  if newStyleName != 'Regular':
    newFullName += " " + newStyleName
  newFullNamePs = remove_whitespace(newFullName)
  set_full_name(font, newFullName, newFullNamePs)

  nameTable = font["name"]
  for rec in nameTable.names:
    rid = rec.nameID
    if rid in (SUBFAMILY_NAME, TYPO_SUBFAMILY_NAME):
      rec.string = newStyleName


def setFamilyName(font, nextFamilyName):
  prevFamilyNames = getFamilyNames(font)
  # if prevFamilyNames[0] == nextFamilyName:
  #   return
  #   # raise Exception("identical family name")

  def renameRecord(nameRecord, prevFamilyNames, nextFamilyName):
    # replaces prevFamilyNames with nextFamilyName in nameRecord
    s = nameRecord.toUnicode()
    for prevFamilyName in prevFamilyNames:
      start = s.find(prevFamilyName)
      if start == -1:
        continue
      end = start + len(prevFamilyName)
      nextFamilyName = s[:start] + nextFamilyName + s[end:]
      nameRecord.string = nextFamilyName
      break
    return s, nextFamilyName

  # postcript name can't contain spaces
  psPrevFamilyNames = []
  for s in prevFamilyNames:
    s = s.strip()
    if s.find(' ') == -1:
      psPrevFamilyNames.append(s)
    else:
      # Foo Bar Baz -> FooBarBaz
      psPrevFamilyNames.append(s.replace(" ", ""))
      # # Foo Bar Baz -> FooBar-Baz
      p = s.rfind(' ')
      s = s[:p] + '-' + s[p+1:]
      psPrevFamilyNames.append(s)

  psNextFamilyName = nextFamilyName.replace(" ", "")
  found_VAR_PS_NAME_PREFIX = False
  nameTable = font["name"]

  for rec in nameTable.names:
    name_id = rec.nameID
    if name_id not in FAMILY_RELATED_IDS:
      # leave uninteresting records unmodified
      continue
    if name_id == POSTSCRIPT_NAME:
      old, new = renameRecord(rec, psPrevFamilyNames, psNextFamilyName)
    elif name_id == TRUETYPE_UNIQUE_ID:
      # The Truetype Unique ID rec may contain either the PostScript Name
      # or the Full Name
      prev_psname = None
      for s in psPrevFamilyNames:
        if s in rec.toUnicode():
          prev_psname = s
          break
      if prev_psname is not None:
        # Note: This is flawed -- a font called "Foo" renamed to "Bar Lol";
        # if this record is not a PS record, it will incorrectly be rename "BarLol".
        # However, in practice this is not a big deal since it's just an ID.
        old, new = renameRecord(rec, [prev_psname], psNextFamilyName)
      else:
        old, new = renameRecord(rec, prevFamilyNames, nextFamilyName)
    elif name_id == VAR_PS_NAME_PREFIX:
      # Variations PostScript Name Prefix.
      # If present in a variable font, it may be used as the family prefix in the
      # PostScript Name Generation for Variation Fonts algorithm.
      # The character set is restricted to ASCII-range uppercase Latin letters,
      # lowercase Latin letters, and digits.
      found_VAR_PS_NAME_PREFIX = True
      old, new = renameRecord(rec, prevFamilyNames, nextFamilyName)
    else:
      old, new = renameRecord(rec, prevFamilyNames, nextFamilyName)
    # print("  %r: '%s' -> '%s'" % (rec, old, new))

  # add name ID 25 "Variations PostScript Name Prefix" if not found
  if not found_VAR_PS_NAME_PREFIX and nextFamilyName.find('Variable') != -1:
    varPSNamePrefix = remove_whitespace(nextFamilyName)
    if font_is_italic(font):
      varPSNamePrefix += 'Italic'
    nameTable.setName(varPSNamePrefix, VAR_PS_NAME_PREFIX, 1, 0, 0)     # mac
    nameTable.setName(varPSNamePrefix, VAR_PS_NAME_PREFIX, 3, 1, 0x409) # windows


def gen_stat(ttfont):
  # builds a STAT table
  # https://learn.microsoft.com/en-us/typography/opentype/spec/stat
  #
  # We are limited to format 2 or 3 records, else Adobe products like InDesign
  # bugs out. See https://github.com/rsms/inter/issues/577
  #
  # build a version 1.1 STAT table with format 2 records:
  buildStatTable(ttfont, stat_axes_format_2(font_is_italic(ttfont)))
  #
  # build a version 1.1 STAT table with format 1 and 3 records:
  #buildStatTable(ttfont, stat_axes_format_3(font_is_italic(ttfont)))
  #
  # build a version 1.2 STAT table with format 4 records:
  #locations = stat_locations(font_is_italic(ttfont))
  #buildStatTable(ttfont, STAT_AXES, locations=locations)


# def fixup_fvar(ttfont):
#   fvar = ttfont['fvar']
#   for a in fvar.axes:
#     if a.axisTag == "wght":
#       a.defaultValue = 400
#       break


# def fixup_os2(ttfont):
#   os2 = ttfont['OS/2']
#   os2.usWeightClass = 400


def main():
  argparser = argparse.ArgumentParser(
    description='Generate STAT table for variable font family')
  a = lambda *args, **kwargs: argparser.add_argument(*args, **kwargs)
  a('--family', metavar='<name>',
    help='Rename family to <name> instead of "Inter Variable"')
  a('-o', '--output', metavar='<file>',
    help='Output font file. Defaults to input file (overwrite)')
  a('input', metavar='<file>', help='Input font file')

  args = argparser.parse_args()

  # load font
  font = TTFont(args.input, recalcBBoxes=False, recalcTimestamp=False)

  # set family name
  if not args.family:
    args.family = "Inter Variable"
  setFamilyName(font, args.family)

  # set style name
  stylename = remove_substring(getStyleName(font), "Display")
  if stylename == '':
    stylename = 'Regular'
  setStyleName(font, stylename)

  # build STAT table
  gen_stat(font)

  # # fixup fvar table (set default wght value)
  # fixup_fvar(font)

  # # fixup OS/2 table (set usWeightClass)
  # fixup_os2(font)

  # save font
  outfile = args.output or args.input
  font.save(outfile)


if __name__ == '__main__':
  main()
