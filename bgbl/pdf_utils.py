from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
import logging
import os
import re
import subprocess
import shutil
import tempfile

from pdfrw import PdfReader, PdfWriter, PdfDict, PdfName, PdfString, PdfTokens

from .models import Publication

logger = logging.getLogger(__name__)


def uncompress_pdf(filename):
    logger.debug('Uncompress PDF file with qpdf %s', filename)
    result = subprocess.run([
        'qpdf', '--stream-data=uncompress', filename, '-'
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError()
    return BytesIO(result.stdout)


def compress_pdf(pdf_bytes):
    logger.debug('Compress PDF file with qpdf')
    f = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    try:
        f.write(pdf_bytes.getvalue())
        f.close()

        result = subprocess.run([
            'qpdf', '--linearize',
            f.name,
            '-'
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            raise RuntimeError()
        return BytesIO(result.stdout)
    finally:
        os.remove(f.name)


@contextmanager
def edit_pdf_doc(filename, backup=True, backup_suffix='_backup'):
    pdf_file = uncompress_pdf(filename)

    doc = PdfReader(pdf_file)

    yield doc

    output = BytesIO()
    outdata = PdfWriter(output)
    outdata.trailer = doc
    outdata.write()
    compressed_output = compress_pdf(output)

    if backup:
        backup_path = filename.replace('.pdf', '%s.pdf' % backup_suffix)
        shutil.move(filename, backup_path)

    with open(filename, 'wb') as f:
        f.write(compressed_output.getvalue())


def remove_watermark(filename, backup_suffix='_watermarked'):
    publication = Publication.objects.get_from_filename(filename)

    with edit_pdf_doc(filename, backup_suffix=backup_suffix) as doc:
        fix_metadata(
            doc, title=publication.title, creation_date=publication.date
        )
        if publication.has_likely_watermark():
            remove_watermark_objects(doc)


def make_pdf_date(value):
    value = value.strftime("%Y%m%d%H%M%S%z")
    if len(value) == 19:
        value = value[:17] + "'" + value[17:]
    return PdfString("(D:%s)" % value)


def fix_metadata(doc, title=None, creation_date=None):
    # Clear any existing XMP meta data
    doc.Root.Metadata = None

    meta = {
        'Creator': 'OffeneGesetze.de',
        'Keywords': 'Amtliches Werk nach §5 UrhG https://offenegesetze.de',
        'ModDate': make_pdf_date(datetime.now()),
    }
    if title is not None:
        meta['Title'] = title
    if creation_date is not None:
        meta['CreationDate'] = make_pdf_date(creation_date)

    for key, val in meta.items():
        if 'Date' not in key:
            val = PdfString.from_unicode(val)
        doc.Info[PdfName(key)] = val


WATERMARK_LINE = (
    '\n(Das Bundesgesetzblatt im Internet: www.bundesgesetzblatt'
    '.de | Ein Service des Bundesanzeiger Verlag www.bundesanzei'
    'ger-verlag.de)Tj'
)


def remove_watermark_objects(doc, filename=None):
    doc = strip_xobjects(doc, exclude_func=is_logo)

    for page_no, page in enumerate(doc.pages, 1):
        stream = page.Contents.stream
        if WATERMARK_LINE in stream:
            stream = stream.replace(WATERMARK_LINE, '')
        else:
            stream, found = complex_watermark_removal(stream)
            if not found:
                logger.warning('No watermark removal: %s page %s',
                               filename, page_no)

        page.Contents = PdfDict()
        page.Contents.stream = stream
        page.Contents.Length = len(page.Contents.stream)


NEEDLE_1 = '(Das Bundesgesetzblatt im Internet'
NEEDLE_2 = 'nzeiger.de)'


def complex_watermark_removal(stream, start_offset=1, end_offset=2):
    found = False
    start = None
    end = None
    for i, token in enumerate(PdfTokens(stream)):
        if NEEDLE_1 in token:
            start = i
            found = True
            continue
        if NEEDLE_2 in token:
            end = i
    tokens = list(PdfTokens(stream))
    if start is None or end is None:
        return '\n'.join(tokens), False
    if tokens[start - 1] == '[':
        start = start - 1
    while tokens[end].upper() != 'TJ':
        end += 1
    end += 1
    return '\n'.join(tokens[:start] + tokens[end:]), found


LOGO_HEIGHT = 26
LOGO_WIDTH = 113
THRESHOLD_RATIO = 0.1
STREAM_IMAGE_PATTERN = (
    '\nq [\d\.]+ [\d\.]+ [\d\.]+ [\d\.]+ '
    '[\d\.]+ [\d\.]+ cm\n{objid} Do\nQ'
)


def is_logo(obj):
    try:
        height = int(obj.Height)
        width = int(obj.Width)
        color_space = str(obj.ColorSpace)
        subtype = str(obj.Subtype)
        if (subtype == '/Image' and
                color_space == '/DeviceRGB' and
                abs(LOGO_HEIGHT - height) / height < THRESHOLD_RATIO and
                abs(LOGO_WIDTH - width) / width < THRESHOLD_RATIO):
            return True
    except Exception as e:
        logger.exception(e)
    return False


def remove_image_from_page(page, objid):
    stream = page.Contents.stream
    stream = re.sub(STREAM_IMAGE_PATTERN.format(objid=objid), '', stream)
    page.Contents = PdfDict()
    page.Contents.stream = stream
    page.Contents.Length = len(page.Contents.stream)


def strip_xobjects(pdf, exclude_func=lambda x: True):
    for i, page in enumerate(pdf.pages):
        if page.Resources.XObject is None:
            continue
        names = list(page.Resources.XObject)
        for name in names:
            obj = page.Resources.XObject[name]
            if exclude_func(obj):
                del page.Resources.XObject[name]
                remove_image_from_page(page, name)
    return pdf
