# 
# reductio ad absurdum
#
# a proof of concept 
# : all programs can be reduced to the same instruction stream.
#

#
# github.com/xoreaxeaxeax/reductio // domas // @xoreaxeaxeax
#

import sys
import hashlib
import re
import os
import subprocess

XFER_SIZE = 4

def ismem(term):
    return "(" in term or "%" not in term

def compose(offset, base, index, scale):
    if not base and not index and not scale:
        return "(%s)" % offset
    elif not index and not scale:
        return "%s(%s)" % (offset, base)
    elif not scale:
        return "%s(%s,%s,1)" % (offset, base, index)
    else:
        return "%s(%s,%s,%s)" % (offset, base, index, scale)

def decompose(term):
    offset = base = index = scale = ""
    r = re.compile(r'(.*)\((%.*),(%.*),(.*)\)')
    if r.match(term):
        (offset,base,index,scale) = r.search(term).groups()
    else:
        r = re.compile(r'(.*)\(,(%.*),(.*)\)')
        if r.match(term):
            (offset,index,scale) = r.search(term).groups()
        else:
            r = re.compile(r'(.*)\((%.*),(%.*)\)') 
            if r.match(term):
                (offset,base,index) = r.search(term).groups()
            else:
                r = re.compile(r'(.*)\((%.*)\)') 
                if r.match(term):
                    (offset,base) = r.search(term).groups()
                else:
                    r = re.compile(r'\((.*)\)') 
                    if r.match(term):
                        (offset,) = r.search(term).groups()
                    else:
                        r = re.compile(r'(.*)') 
                        if r.match(term):
                            (offset,) = r.search(term).groups()
                        else:
                            raise Exception 
    return (offset, base, index, scale)

BAR_LENGTH = 50
BAR_REFRESH = .001 # .001
def progress(p, l):
    if l < 1:
        l = 1
    if p / float(l) > progress.last + BAR_REFRESH or p == l:
        progress.last = p / float(l)
        sys.stdout.write(
                " [%s%s] %6.1f%%" % 
                    ("-" * (p * BAR_LENGTH / l),
                     " " * (BAR_LENGTH - p * BAR_LENGTH / l),
                     (progress.last * 100))
                    )
        sys.stdout.write("\b" * (BAR_LENGTH + 3 + 8))
        sys.stdout.flush()
    if p == l:
        progress.last = 0
progress.last = 0

def load(s):
    with open(s) as f:
        asm = f.readlines()
    return asm

# aes becomes a 2gb file.  gnu assembler doesn't like that.
# break it into pieces. 
# (hence the 'globals' throughout this - 
#  everything needs to be visible to linker)
MAX_ASM_LINES = 100000
def break_write(s, asm):
    i = 0
    c = 0
    while c < len(asm):
        with open("%s%03d" % (s, i), 'w') as f:
            f.write(".data\n") # super-hack - as will assume .text
            for p, l in enumerate(asm[c:c+MAX_ASM_LINES]):
                progress(c, len(asm)-1)
                if p != 0 and ".balign" in l:
                    # another hack.  this one was frustrating and cost hours
                    # to track down.  the gas .align directive pads the
                    # current location _and_ forces an alignment of the
                    # entire section in the resulting object.  although this
                    # makes sense in hindsight, it isn't documented, and
                    # caused a lot of mysterious breaking (when a table not
                    # containing an .align gets split across multiple
                    # objects, and a subsequent .align causes padding to be
                    # injected into the middle of the table to try to align
                    # the entire section).  to "fix" - ensure the alignment
                    # does not occur in the middle of an object.
                    break
                f.write(l)
                c = c + 1
            # assume global directives are always above their label
            # (not a safe assumption)
            # and keep directive and label together
            if asm[c-1].startswith(".glob"):
                f.write(asm[c])
                c = c + 1
        i = i + 1
    return ["%s%03d" % (s, k) for k in range(i)]

def write(s, asm):
    with open(s, 'w') as f:
        for p, l in enumerate(asm):
            progress(p, len(asm)-1)
            f.write(l)

# pass 0:
# separate execution loop from environment setup
def remove_prologue(asm):
    pasm = []
    prologue = []
    found_prologue = False
    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        if "master_loop" in l:
            found_prologue = True
        if found_prologue:
            pasm.append(l)
        else:
            prologue.append(l)
    if not found_prologue:
        for l in prologue:
            pasm.append(l)
        prologue = []

    return [pasm,prologue]

# pass 1:
# replace all constant references with memory references instead
def pass_1(asm):
    pasm = []
    constants = set()
    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        if l.startswith("mov") and "<LCI>" not in l:
            pasm.append("# pass 1 (constants) > " + l)

            tok = l.find(",", l.find(")"))
            if tok == -1:
                tok = l.find(",")
            source = l[l.index(" "):tok].strip()
            dest = l[tok+1:].strip()

            # NOTE: requires M/o/Vfuscator to only produce dword constants
            if source.startswith("$"):
                pasm.append("#constant> " + l)

                # have to jump through some hoops due to as and ld limitations
                # on absolutes 
                c = hashlib.md5(source[1:]).hexdigest()
                pasm.append(".section .data\n")
                #pasm.append(".ifndef .C%s\n" % c)
                if source[1:] not in constants:
                    pasm.append(".global .C%s\n" % (c)) # split global
                    pasm.append(".C%s: .long %s\n" % (c, source[1:]))
                    constants.add(source[1:])
                #pasm.append(".endif\n")
                pasm.append(".section .text\n")
                pasm.append("movl (.C%s), %%ebp\n" % c)
                pasm.append("movl %%ebp, %s\n" % dest)
            else:
                pasm.append(l)
        else:
            pasm.append(l)
    return pasm

# pass 2:
# replace all register to register transfers
def pass_2(asm):
    pasm=[]
    pasm.append(".section .data\n")
    pasm.append(".global .r2r\n") # split global
    pasm.append(".r2r: .long 0\n")
    pasm.append(".section .text\n")

    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        if l.startswith("mov") and "<LCI>" not in l:
            pasm.append("# pass 2 (r2r) > " + l)

            tok = l.find(",", l.find(")"))
            if tok == -1:
                tok = l.find(",")
            source = l[l.index(" "):tok].strip()
            dest = l[tok+1:].strip()

            if l.startswith("movb"):
                s = "b"
            elif l.startswith("movw"):
                s = "w"
            elif l.startswith("movl"):
                s = "l"

            if source.startswith("%") and dest.startswith("%"):
                pasm.append("mov%s %s, (.r2r)\n" % (s, source))
                pasm.append("mov%s (.r2r), %s\n" % (s, dest))
            else:
                pasm.append(l)

        else:
            pasm.append(l)
    return pasm

# pass 3:
# pad .data and .bss sections to allow data accesses to extend past boundaries
def pass_3(asm):
    pasm=[]
    pasm.append("# section padding\n")
    pasm.append(".section .data\n")
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".long 0\n")
    pasm.append(".section .bss\n")
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".long 0\n")
    pasm.append("# end padding\n")
    pasm.append("# mov32 shuffle space\n")
    pasm.append(".section .data\n")
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".global .s_a%d\n" % i) # split global
        pasm.append(".s_a%d: .byte 0\n" % i)
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".global .s_b%d\n" % i) # split global
        pasm.append(".s_b%d: .byte 0\n" % i)
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".global .s_c%d\n" % i) # split global
        pasm.append(".s_c%d: .byte 0\n" % i)
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".global .r_a%d\n" % i) # split global
        pasm.append(".r_a%d: .byte 0\n" % i)
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".global .r_b%d\n" % i) # split global
        pasm.append(".r_b%d: .byte 0\n" % i)
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".global .r_c%d\n" % i) # split global
        pasm.append(".r_c%d: .byte 0\n" % i)
    pasm.append("# end shuffle space\n")
    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        pasm.append(l)
    pasm.append("# section padding\n")
    pasm.append(".section .data\n")
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".long 0\n")
    pasm.append(".section .bss\n")
    for i in xrange(0,(XFER_SIZE+1)/4):
        pasm.append(".long 0\n")
    pasm.append("# end padding\n")

    return pasm

# pass 4:
# convert all transfers to 32 bits
def pass_4(asm):
    pasm=[]
    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        if l.startswith("mov") and "<LCI>" not in l:
            pasm.append("# pass 4 (32b) > " + l)

            tok = l.find(",", l.find(")"))
            if tok == -1:
                tok = l.find(",")
            source = l[l.index(" "):tok].strip()
            dest = l[tok+1:].strip()

            # warning: ebp used in a previous pass to load immediates.  it's
            # okay since it was loading 32 bit values, and won't be translated here.
            sr = "%ebp"

            if l.startswith("movb"):
                if source.startswith("%"):
                    # r8 -> m8
                    r32 = "%%e%cx" % source[1]
                    m = dest[dest.index("(")+1:dest.index(")")]
                    if not "%" in m:
                        # "(b)" format
                        b = m
                        si = ""
                    else:
                        # "b(si)" format
                        b = dest[:dest.index("(")]
                        si = "(" + m + ")"

                    pasm.append("movl %s, (.s_b0)\n" % r32)

                    pasm.append("movl %s%+d%s, %s\n" % (b, -XFER_SIZE, si, sr))

                    if source[2] == 'h':
                        pasm.append("movl %s, (.s_b0%+d)\n" % (sr, -XFER_SIZE+1))
                        pasm.append("movl (.s_b0%+d), %s\n" % (-XFER_SIZE+2, sr))
                    elif source[2] == 'l':
                        pasm.append("movl %s, (.s_b0%+d)\n" % (sr, -XFER_SIZE))
                        pasm.append("movl (.s_b0%+d), %s\n" % (-XFER_SIZE+1, sr))
                    else:
                        raise Exception

                    pasm.append("movl %s, %s%+d%s\n" % (sr, b, -XFER_SIZE+1, si))

                else:
                    # m8 -> r8
                    r32 = "%%e%cx" % dest[1]
                    m = source[source.index("(")+1:source.index(")")]
                    if not "%" in m:
                        # "(b)" format
                        b = m
                        si = ""
                    else:
                        # "b(si)" format
                        b = source[:source.index("(")]
                        si = "(" + m + ")"

                    pasm.append("movl %s, (.r_b0)\n" % r32)

                    if dest[2] == 'h':
                        pasm.append("movl %s%s, %s\n" % (b, si, sr))
                        pasm.append("movl %s, (.s_b0+1)\n" % (sr))
                        pasm.append("movl (.r_b0+2), %s\n" % (sr))
                        pasm.append("movl %s, (.s_b0+2)\n" % (sr))
                        pasm.append("movl (.r_b0%+d), %s\n" % (sr, -XFER_SIZE+1))
                        pasm.append("movl %s, (.s_b0%+d)\n" % (sr, -XFER_SIZE+1))
                    elif dest[2] == 'l':
                        pasm.append("movl %s%s, %s\n" % (b, si, sr))
                        pasm.append("movl %s, (.s_b0)\n" % (sr))
                        pasm.append("movl (.r_b0+1), %s\n" % (sr))
                        pasm.append("movl %s, (.s_b0+1)\n" % (sr))
                    else:
                        raise Exception

                    pasm.append("movl (.s_b0), %s\n" % r32)

            elif l.startswith("movw"):
                if source.startswith("%"):
                    # r16 -> m16
                    r32 = "%%e%cx" % source[1]
                    m = dest[dest.index("(")+1:dest.index(")")]
                    if not "%" in m:
                        # "(b)" format
                        b = m
                        si = ""
                    else:
                        # "b(si)" format
                        b = dest[:dest.index("(")]
                        si = "(" + m + ")"

                    pasm.append("movl %s, (.s_b0)\n" % r32)

                    pasm.append("movl %s%+d%s, %s\n" % (b, -XFER_SIZE, si, sr))

                    pasm.append("movl %s, (.s_b0%+d)\n" % (sr, -XFER_SIZE))
                    pasm.append("movl (.s_b0%+d), %s\n" % (-XFER_SIZE+2, sr))

                    pasm.append("movl %s, %s%+d%s\n" % (sr, b, -XFER_SIZE+2, si))

                else:
                    # m16 -> r16
                    r32 = "%%e%cx" % dest[1]
                    m = source[source.index("(")+1:source.index(")")]
                    if not "%" in m:
                        # "(b)" format
                        b = m
                        si = ""
                    else:
                        # "b(si)" format
                        b = source[:source.index("(")]
                        si = "(" + m + ")"

                    pasm.append("movl %s, (.r_b0)\n" % r32)

                    pasm.append("movl %s%s, %s\n" % (b, si, sr))
                    pasm.append("movl %s, (.s_b0)\n" % (sr))
                    pasm.append("movl (.r_b0+2), %s\n" % (sr))
                    pasm.append("movl %s, (.s_b0+2)\n" % (sr))

                    pasm.append("movl (.s_b0), %s\n" % r32)

            elif l.startswith("movl"):
                pasm.append(l)

        else:
            pasm.append(l)

    return pasm

# pass 5: convert all addressing to base + offset addressing
# e.g.: [eax+4*ebx+12345678] -> [ecx+12345678]
# This may not be the actual desired addressing mode, but it is much easier to
# translate to other modes after initially converted to base/offset
def pass_5(asm):
    pasm=[]
    pasm.append(".section .data\n")
    pasm.append(".global .eax\n") # split global
    pasm.append(".eax: .long 0\n")
    pasm.append(".global .ebx\n") # split global
    pasm.append(".ebx: .long 0\n")
    pasm.append(".global .ecx\n") # split global
    pasm.append(".ecx: .long 0\n")
    pasm.append(".global .edx\n") # split global
    pasm.append(".edx: .long 0\n")
    pasm.append(".global .esi\n") # split global
    pasm.append(".esi: .long 0\n")
    pasm.append(".global .edi\n") # split global
    pasm.append(".edi: .long 0\n")
    pasm.append(".global .ebp\n") # split global
    pasm.append(".ebp: .long 0\n")
    pasm.append(".global .esp\n") # split global
    pasm.append(".esp: .long 0\n")
    pasm.append(".global .zero\n") # split global
    pasm.append(".zero: .long 0\n")
    pasm.append(".long 0\n")
    pasm.append(".global .chop\n") # split global
    pasm.append(".chop: .long 0\n")
    pasm.append(".long 0\n")
    pasm.append(".global .sum_x\n") # split global
    pasm.append(".sum_x: .long 0\n")

    for i in (0,1,2,3):
        pasm.append(".global .ind%dl\n" % i) # split global
        pasm.append(".ind%dl: .long 0\n" % i)
        pasm.append(".global .ind%dh\n" % i) # split global
        pasm.append(".ind%dh: .long 0\n" % i)

    pasm.append(".long 0\n")
    pasm.append(".global .oraddr\n") # split global
    pasm.append(".oraddr: .long 0\n")
    pasm.append(".long 0\n")

    pasm.append(".long 0\n")
    pasm.append(".global .orresult\n") # split global
    pasm.append(".orresult: .long 0\n")
    pasm.append(".long 0\n")

    for k in (0,1,2,3):
        pasm.append(".global .scale%dl\n" % (2**k)) # split global
        pasm.append(".scale%dl:\n" % (2**k))
        for i in xrange(0,256):
            pasm.append(".byte 0x%02x\n" % ((i<<k)&0xff))
        pasm.append(".global .scale%dh\n" % (2**k)) # split global
        pasm.append(".scale%dh:\n" % (2**k))
        for i in xrange(0,256):
            pasm.append(".byte 0x%02x\n" % (((i<<k)&0xff00)>>8))

    pasm.append(".global .riscor\n") # split global
    pasm.append(".riscor:\n")
    for i in xrange(0,0x10000):
        pasm.append(".byte 0x%02x\n" % ((i&0xff)|((i&0xff00)>>8)))

    pasm.append(".long 0\n")
    pasm.append(".global .sumaddr\n") # split global
    pasm.append(".sumaddr: .long 0\n")
    pasm.append(".long 0\n")

    pasm.append(".long 0\n")
    pasm.append(".global .sumcarry\n") # split global
    pasm.append(".sumcarry: .long 0\n")
    pasm.append(".long 0\n")

    pasm.append(".long 0\n")
    pasm.append(".global .sumresult\n") # split global
    pasm.append(".sumresult: .long 0\n")
    pasm.append(".long 0\n")

    for i in (0,1,2,3):
        pasm.append(".global .sum%dl\n" % i) # split global
        pasm.append(".sum%dl: .long 0, 0\n" % i)
        pasm.append(".global .sum%dh\n" % i) # split global
        pasm.append(".sum%dh: .long 0, 0\n" % i)

    pasm.append(".global .riscaddl\n") # split global
    pasm.append(".riscaddl:\n")
    for i in xrange(0,0x20000):
        pasm.append(".byte 0x%02x\n" % \
                (((i&0xff)+((i&0xff00)>>8)+((i&0x10000)>>16))&0xff))
    pasm.append(".global .riscaddh\n") # split global
    pasm.append(".riscaddh:\n")
    for i in xrange(0,0x20000):
        pasm.append(".byte 0x%02x\n" % \
                (((i&0xff)+((i&0xff00)>>8)+((i&0x10000)>>16))>>8))

    pasm.append(".section .text\n")

    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        if l.startswith("mov") and "<LCI>" not in l:
            pasm.append("# pass 5 (risc) > " + l)

            match = re.search(r'^mov([bwl])\s+(.*)\s*,\s*([^#]*).*\n$', l)

            (size, source, dest) = match.groups()

            if ismem(source):
                (offset, base, index, scale) = decompose(source)
            else:
                (offset, base, index, scale) = decompose(dest)

            pasm.append("movl .zero(%edi), %esi\n")

            if index and scale:
                for b in ('l','h'):
                    for i in (0,1,2,3):
                        # get byte
                        pasm.append("movl .%s(%%edi), %%esi\n" % index[1:])
                        pasm.append("movl %esi, .chop(%edi)\n")
                        pasm.append("movl .zero(%edi), %esi\n")
                        pasm.append("movl %%esi, .chop+%d(%%edi)\n" % (i+1))
                        pasm.append("movl .chop+%d(%%edi), %%esi\n" % (i))

                        # shift
                        pasm.append("movl .scale%s%c(%%esi), %%esi\n" % (scale, b))
                        pasm.append("movl %esi, .chop(%edi)\n")
                        pasm.append("movl .zero(%edi), %esi\n")
                        pasm.append("movl %esi, .chop+1(%edi)\n")
                        pasm.append("movl .chop(%edi), %esi\n")

                        # save
                        pasm.append("movl %%esi, .ind%d%c(%%edi)\n" % (i, b))

                pasm.append("movl .ind0l(%edi), %esi\n")
                pasm.append("movl %esi, .orresult(%edi)\n")
                for i in (1,2,3):
                    pasm.append("movl .ind%dh(%%edi), %%esi\n" % (i-1))
                    pasm.append("movl %esi, .oraddr(%edi)\n")
                    pasm.append("movl .ind%dl(%%edi), %%esi\n" % (i))
                    pasm.append("movl %esi, .oraddr+1(%edi)\n")
                    pasm.append("movl .oraddr(%edi), %esi\n")
                    pasm.append("movl .riscor(%esi), %esi\n")
                    pasm.append("movl %%esi, .orresult+%d(%%edi)\n" % i)

                pasm.append("movl .orresult(%edi), %esi\n")

            elif index:
                pasm.append("movl .%s(%%edi), %s\n" % (index[1:], "%esi"))

            if base and index:
                pasm.append("movl %esi, .sum_x(%edi)\n")

                pasm.append("movl .zero(%edi), %esi\n")
                pasm.append("movl %esi, .sumcarry(%edi)\n")

                for i in (0,1,2,3):
                    # merge
                    pasm.append("movl .%s(%%edi), %%esi\n" % base[1:])
                    pasm.append("movl %esi, .chop(%edi)\n")
                    pasm.append("movl .chop+%d(%%edi), %%esi\n" % (i))
                    pasm.append("movl %esi, .sumaddr(%edi)\n")

                    pasm.append("movl .sum_x+%d(%%edi), %%esi\n" % (i))
                    pasm.append("movl %esi, .sumaddr+1(%edi)\n")

                    pasm.append("movl .sumcarry(%edi), %esi\n")
                    pasm.append("movl %esi, .sumaddr+2(%edi)\n")

                    # sum
                    pasm.append("movl .sumaddr(%edi), %esi\n")
                    pasm.append("movl .riscaddl(%esi), %esi\n")
                    pasm.append("movl %%esi, .sumresult+%d(%%edi)\n" % i)

                    pasm.append("movl .sumaddr(%edi), %esi\n")
                    pasm.append("movl .riscaddh(%esi), %esi\n")
                    pasm.append("movl %esi, .sumcarry(%edi)\n")
                    pasm.append("movl .zero(%edi), %esi\n")
                    pasm.append("movl %esi, .sumcarry+1(%edi)\n")

                pasm.append("movl .sumresult(%edi), %esi\n")

            elif base:
                pasm.append("movl .%s(%%edi), %%esi\n" % base[1:])

            if ismem(source):
                pasm.append("movl.d32 %s(%s), %s\n" % (offset, "%esi", "%esi"))
                pasm.append("movl %%esi, .%s(%%edi)\n" % dest[1:])

                if "<REQ>" in l:
                    pasm.append("# <REQ>\n")
                    pasm.append("movl .%s(%%edi), %s\n" % (dest[1:], dest))

            else:
                if "<REQ>" in l:
                    pasm.append("# <REQ>\n")
                    pasm.append("movl %s, .%s(%%edi)\n" % (source, source[1:]))

                pasm.append("movl .%s(%%edi), %%edx\n" % (source[1:]))
                pasm.append("movl.d32 %s, %s(%s)\n" % ("%edx", offset, "%esi"))

        else:
            pasm.append(l)

    return pasm

# pass 6:
# - alternate reads and writes, standardize instruction format
def pass_6(asm):
    pasm=[]
    pasm.append(".section .data\n")
    pasm.append(".global .scratch_rw\n") # split global
    pasm.append(".scratch_rw: .long 0\n")
    pasm.append(".section .text\n")
    last_write = False

    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        if l.startswith("mov") and "<LCI>" not in l:
            pasm.append("# pass 6 (alternate) > " + l)

            match = re.search(r'^movl[^\s]*\s+(.*)\s*,\s*([^#]*).*\n$', l)

            (source, dest) = match.groups()

            if ismem(source):
                (offset, base, index, scale) = decompose(source)
            else:
                (offset, base, index, scale) = decompose(dest)

            assert index == ""
            assert scale == ""

            if offset == "":
                offset = "0"
            base = "(" + base + ")"
            if ismem(source):
                if not last_write:
                    pasm.append("movl.d32 %edi, .scratch_rw(%edi)\n")
                pasm.append("movl.d32 %s%s, %s\n" % (offset, base, dest))
                last_write = False
            else:
                if last_write:
                    pasm.append("movl.d32 .scratch_rw(%edi), %edi\n")
                pasm.append("movl.d32 %s, %s%s\n" % (source, offset, base))
                last_write = True
        else:
            pasm.append(l)

    if last_write:
        pasm.append("movl.d32 .scratch_rw(%edi), %edi\n")

    return pasm

def reduce(s, prologue):
    pasm = []

    # (hack) keep data starting locations consistent to ensure identical
    # addresses in instruction stream
    # (see note on gnu as quirk later)
    # (semicolon hack ensures alignment and section directives don't get split
    # across files by break_write)
    pasm.append(".section .data ; .balign 0x10000\n")

    # (hack) keep text starting locations consistent to ensure identical
    # addresses in instruction stream
    # (see note on gnu as quirk later)
    # (semicolon hack ensures alignment and section directives don't get split
    # across files by break_write)
    pasm.append(".section .text ; .balign 0x10000\n")

    pasm.append("### prologue ###\n")
    for l in prologue:
        pasm.append(l)
    pasm.append("### end prologue ###\n")

    # patch up issue with mov_extern that i'm too lazy to fix
    # (assumes compiling with -Wf--no-mov-extern)
    # (this is for the old version using fault-linking)
    # also fixes issue when manually omitting crtf during linking
    pasm.append(".global dispatch\n")
    pasm.append("dispatch:\n")

    # virtual registers and selectors
    v_regs = ["eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"]
    pasm.append(".section .data\n")
    for r in v_regs:
        pasm.append(".global .v_%s\n" % r) # split global
        pasm.append(".v_%s: .long 0\n" % r)
    pasm.append(".global .v_reg\n") # split global
    pasm.append(".v_reg: .long %s\n" % ",".join(".v_" + s for s in v_regs))
    # selector references, allows unconditional dereference in sim loop
    for r in v_regs:
        pasm.append(".global .vv_%s\n" % r) # split global
        pasm.append(".vv_%s: .long .v_%s\n" % (r, r))
    pasm.append(".global .vv_reg\n") # split global
    pasm.append(".vv_reg: .long %s\n" % ",".join(".vv_" + s for s in v_regs))
    pasm.append(".section .text\n")

    operands = []
    returns = []
    mcount = 0

    operands.append(".global .a_0") # split global
    operands.append(".a_0:")

    last_branch_index = -1

    for p, l in enumerate(asm):
        progress(p, len(asm)-1)
        if l.startswith("mov") and "<LCI>" not in l:
            pasm.append("#S> " + l)
            match = re.search(r'^movl[^\s]*\s+(.*)\s*,\s*([^#]*).*\n$', l)

            (source, dest) = match.groups()

            if ismem(source):
                (offset, base, index, scale) = decompose(source)
            else:
                (offset, base, index, scale) = decompose(dest)

            assert index == ""
            assert scale == ""

            if ismem(source):
                # read
                operands.append("# %s (%d)" % (l.strip(), mcount))
                operands.append(".v_" + base[1:])
                operands.append(offset)
                operands.append(".vv_" + dest[1:])
                operands.append("0")
            else:
                # write
                operands.append("# %s (%d)" % (l.strip(), mcount))
                operands.append(".vv_" + source[1:])
                operands.append("0")
                operands.append(".v_" + base[1:])
                operands.append(offset)
            operands.append(".loop")
            operands.append(".loop")
            last_branch_index = len(operands) - 1 
            mcount = mcount + 1
            operands.append(".a_" + str(mcount))
            operands.append(".global .a_" + str(mcount)) # split global
            operands.append(".a_" + str(mcount)  + ":")
        elif l.startswith(".LCI") or "<LCI>" in l:
            # internal label (branching)
            operands.append(".global " + l.split(":")[0]) # split global
            operands.append(l)
        elif l.startswith(".LCE") or "<LCE>" in l:
            # external label (return address)
            returns.append(".global " + l.split(":")[0] + "\n") # split global
            returns.append(l)
        elif l.startswith(".LCS") or "<LCS>" in l:
            # label used by symbol
            pasm.append(".global " + l.split(":")[0] + "\n") # split global
            pasm.append(l)
        elif l.startswith(".size"):
            # discard size directives
            pass
        elif l.startswith("cmp"):
            # discard comparisons (handled by je)
            pass
        elif l.startswith("je"):
            # accumulate non-movfuscated calls
            operands[last_branch_index] = l[3:] + " # target"
        else:
            pasm.append(l)

    # so hacky, fix this...
    #operands.remove(".a_" + str(mcount)  +":")
    #operands = [o.replace(".a_" + str(mcount) , ".a_0") for o in operands]
    assert operands[last_branch_index+1] == ".a_" + str(mcount)
    assert operands[last_branch_index+2] == ".global .a_" + str(mcount)
    assert operands[last_branch_index+3] == ".a_" + str(mcount) + ":"
    operands[last_branch_index+1] = ".a_0"
    #del operands[last_branch_index+2:last_branch_index+4]
    del operands[last_branch_index+2]
    del operands[last_branch_index+2]

    pasm.append(".section .text\n")
    pasm.append("movl $.operands, %esi\n")

    # version for linking by faults
    '''
    pasm.append(".loop:\n")

    pasm.append("movl %eax, .v_eax\n")
    pasm.append("movl .v_esp, %esp\n")

    pasm.append("movl 0(%esi), %ebx\n")
    pasm.append("movl (%ebx), %ebx\n")
    pasm.append("addl 4(%esi), %ebx\n")
    pasm.append("movl (%ebx), %ebx\n")

    for r in returns:
        pasm.append(r)

    pasm.append("movl 8(%esi), %edx\n")
    pasm.append("movl (%edx), %edx\n")
    pasm.append("addl 12(%esi), %edx\n")
    pasm.append("movl %ebx, (%edx)\n")
    pasm.append("movl 24(%esi), %esi\n")

    pasm.append("jmp .loop\n")
    '''

    # version for linking by jumps
    # (simple version)
    '''
    pasm.append("movl %eax, .v_eax\n")

    pasm.append("movl 0(%esi), %ebx\n")
    pasm.append("movl (%ebx), %ebx\n")
    pasm.append("addl 4(%esi), %ebx\n")
    pasm.append("movl (%ebx), %ebx\n")

    pasm.append("movl 8(%esi), %edx\n")
    pasm.append("movl (%edx), %edx\n")
    pasm.append("addl 12(%esi), %edx\n")
    pasm.append("movl %ebx, (%edx)\n")

    pasm.append("movl (on), %edx\n")
    pasm.append("shl $2, %edx\n")
    pasm.append("addl %esi, %edx\n")
    pasm.append("movl 16(%edx), %edx\n")

    pasm.append("movl 24(%esi), %esi\n")

    pasm.append("movl .v_esp, %esp\n")
    pasm.append("jmp *%edx\n")
    '''

    # version for linking by jumps
    # (reduced version)
    for r in returns:
        pasm.append(r)

    pasm.append(".global .loop\n") # split global
    pasm.append(".loop:\n")

    pasm.append("movl 24(%esi), %esi\n")

    pasm.append("movl %eax, .v_eax\n")

    pasm.append("movl 0(%esi), %ebx\n")
    pasm.append("movl (%ebx), %ebx\n")
    pasm.append("addl 4(%esi), %ebx\n")
    pasm.append("movl (%ebx), %ebx\n")

    pasm.append("movl 8(%esi), %edx\n")
    pasm.append("movl (%edx), %edx\n")
    pasm.append("addl 12(%esi), %edx\n")
    pasm.append("movl %ebx, (%edx)\n")

    pasm.append("movl (on), %edx\n")

    pasm.append("movl .v_esp, %esp\n")
    pasm.append("jmp *16(%esi,%edx,4)\n")

    pasm.append(".section .data\n")

    # (hack) keep data starting locations consistent to ensure identical
    # addresses in instruction stream
    # (see note on gnu as quirk later)
    # (semicolon hack ensures alignment and section directives don't get split
    # across files by break_write)
    pasm.append(".section .data ; .balign 0x10000\n")

    # allow first chunk skip
    pasm.append(".long .operands\n")
    pasm.append(".long .operands\n")
    pasm.append(".long .operands\n")
    pasm.append(".long .operands\n")
    pasm.append(".long .operands\n")
    pasm.append(".long .operands\n")

    pasm.append(".global .operands\n")
    pasm.append(".operands:\n")

    for p, l in enumerate(operands):
        progress(p, len(operands)-1)
        if l.startswith("#"):
            pasm.append(l + "\n")
        elif l.startswith(".glob"):
            pasm.append(l + "\n")
        elif ":" in l:
            pasm.append(l + "\n")
        else:
            pasm.append(".long %s\n" % l)

    return pasm

if subprocess.call("type movcc", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) != 0:
    print "Reduction requires installing the M/o/Vfuscator."
    print ""
    print "git clone https://github.com/xoreaxeaxeax/movfuscator"
    print "cd movfuscator"
    print "./build.sh"
    print "sudo ./install.sh"
    exit(1)

mov_install=subprocess.Popen("readlink -f `which movcc`", shell=True, stdout=subprocess.PIPE).communicate()[0]
mov_dir=os.path.dirname(mov_install)

c_file=sys.argv[1]
e_file=os.path.splitext(c_file)[0]
s_file=e_file+".s"
o_file=e_file+".o"
linker_args=sys.argv[2:]

print "compiling..."
command=\
    "movcc "\
    "%s "\
    "-S "\
    "-Wf--crt0 "\
    "-Wf--no-mov-loop "\
    "-Wf--no-mov-extern "\
    "-Wf--q "\
    "-o %s"\
    % (c_file, s_file)
os.system(command)
print "...done"

# reduce
print "reducing... "

print "\tloading... "
asm=load(s_file)

sys.stdout.write("\tprologue... ")
[asm,prologue]=remove_prologue(asm)
sys.stdout.write("\n")

sys.stdout.write("\tpass 1...   ")
asm=pass_1(asm)
sys.stdout.write("\n")

sys.stdout.write("\tpass 2...   ")
asm=pass_2(asm)
sys.stdout.write("\n")

sys.stdout.write("\tpass 3...   ")
asm=pass_3(asm)
sys.stdout.write("\n")

sys.stdout.write("\tpass 4...   ")
asm=pass_4(asm)
sys.stdout.write("\n")

sys.stdout.write("\tpass 5...   ")
asm=pass_5(asm)
sys.stdout.write("\n")

sys.stdout.write("\tpass 6...   ")
asm=pass_6(asm)
sys.stdout.write("\n")

sys.stdout.write("\treduce...   ")
asm=reduce(asm, prologue)
sys.stdout.write("\n")

sys.stdout.write("\twrite...    ")
s_files=break_write(s_file, asm)
sys.stdout.write("\n")

# assemble
o_files = []
sys.stdout.write("\tassemble... ")
for p, l in enumerate(s_files):
    progress(p, len(s_files)-1)
    o = "%s%03d" % (o_file, p)
    o_files.append(o)
    command="as --32 %s -o %s" % (l, o)
    os.system(command)
sys.stdout.write("\n")

# link
sys.stdout.write("\tlink... ")
sys.stdout.flush()
command=\
    "ld -melf_i386 -dynamic-linker /lib/ld-linux.so.2 "\
    "-L %s/ "\
    "-L %s/gcc/32/ "\
    "-lgcc "\
    "-lc "\
    "-lm "\
    "-s "\
    "%s/crtd.o "\
    "%s "\
    "%s "\
    "-o %s"\
    % (mov_dir, mov_dir, mov_dir, " ".join(linker_args), " ".join(o_files), e_file)
os.system(command)
sys.stdout.write("\n")

print "...done "
