/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Static layout for the N7 probe.  Sections sit at their final relative
 * virtual addresses, above one page of PE headers, so n7_elf2pe.py maps
 * them one-to-one.  Read-only data rides in .text (read and execute)
 * and .bss in .data (read and write); nothing else is allocated.
 */
OUTPUT_FORMAT("elf64-littleaarch64")
OUTPUT_ARCH(aarch64)
ENTRY(efi_main)

SECTIONS
{
	. = 0x1000;
	.text : {
		*(.text .text.*)
		*(.rodata .rodata.*)
	}
	. = ALIGN(0x1000);
	.data : {
		*(.data .data.*)
		*(.bss .bss.*)
		*(COMMON)
	}
	/DISCARD/ : {
		*(.comment)
		*(.note .note.*)
		*(.eh_frame .eh_frame_hdr)
		*(.interp .dynamic .dynsym .dynstr .hash .gnu.hash)
	}
}
