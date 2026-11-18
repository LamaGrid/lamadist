/* SPDX-License-Identifier: Apache-2.0 */
/*
 * N7 write probe: a test-only UEFI application, signed by the db key,
 * that runs in place of the removable-media loader before
 * ExitBootServices.  It is the only code in the N7 write test that
 * reaches the firmware's boot-time SetVariable.  It prints one line per
 * result on the console and then chain-loads systemd-boot, so the Linux
 * part of the test runs in the same boot.
 *
 * Order: read PK, KEK, db, and dbx (CRC-32 of each body); run every
 * payload row through SetVariable; L1, LoadImage of an image that only
 * the KEK key signed, which db trusts only if the S-db append worked;
 * S-PK last, so PK is still set for L1; read the variables again;
 * chain-load \n7\sdboot.efi.
 *
 * Each payload file \n7\<row>.bin holds the 4-byte little-endian
 * attributes and then the data, the efivarfs layout, so both parts of
 * the test write the same bytes.  X-PK is the 4 zero bytes alone: an
 * attribute-free, zero-length write, which is a delete.
 *
 * Freestanding (ADR 0017): no header, no C library, no libgcc.  The
 * declarations below cover only what the probe calls; the static
 * assertions pin their offsets to the UEFI specification.  Everything
 * is addressed PC-relative, so there must be no table of pointers in
 * static data: the build refuses any relocation that needs a load-time
 * fix, and the rows are straight-line calls for that reason.
 */

typedef unsigned char UINT8;
typedef unsigned short UINT16;
typedef unsigned int UINT32;
typedef unsigned long long UINT64;
typedef unsigned long UINTN;
typedef UINT16 CHAR16;
typedef UINTN EFI_STATUS;
typedef void *EFI_HANDLE;
typedef UINT8 BOOLEAN;

_Static_assert(sizeof(UINTN) == 8, "AArch64 LP64 only");
_Static_assert(sizeof(void *) == 8, "AArch64 LP64 only");

#define EFIAPI /* AArch64: the UEFI calling convention is AAPCS64 */
#define NULL ((void *)0)
#define offsetof(t, m) __builtin_offsetof(t, m)

#define EFI_SUCCESS 0UL
#define EFI_ERROR_BIT (1UL << 63)
#define EFI_BUFFER_TOO_SMALL (EFI_ERROR_BIT | 5UL)
#define EFI_NOT_FOUND (EFI_ERROR_BIT | 14UL)
#define EFI_FILE_MODE_READ 0x1ULL
#define EFI_LOADER_DATA 2U

/* One payload file at most; the largest signed payload is under 4 KiB. */
#define FILE_CAP (64UL * 1024UL)
#define VAR_CAP (64UL * 1024UL)

typedef struct {
	UINT32 Data1;
	UINT16 Data2;
	UINT16 Data3;
	UINT8 Data4[8];
} EFI_GUID;

typedef struct {
	UINT64 Signature;
	UINT32 Revision;
	UINT32 HeaderSize;
	UINT32 CRC32;
	UINT32 Reserved;
} EFI_TABLE_HEADER;

typedef struct SIMPLE_TEXT_OUTPUT SIMPLE_TEXT_OUTPUT;
struct SIMPLE_TEXT_OUTPUT {
	void *Reset;
	EFI_STATUS(EFIAPI *OutputString)(SIMPLE_TEXT_OUTPUT *This, const CHAR16 *String);
};

typedef struct {
	EFI_TABLE_HEADER Hdr;
	void *GetTime;
	void *SetTime;
	void *GetWakeupTime;
	void *SetWakeupTime;
	void *SetVirtualAddressMap;
	void *ConvertPointer;
	EFI_STATUS(EFIAPI *GetVariable)(const CHAR16 *Name, const EFI_GUID *Vendor,
					UINT32 *Attributes, UINTN *DataSize, void *Data);
	void *GetNextVariableName;
	EFI_STATUS(EFIAPI *SetVariable)(const CHAR16 *Name, const EFI_GUID *Vendor,
					UINT32 Attributes, UINTN DataSize, const void *Data);
} EFI_RUNTIME_SERVICES;

typedef struct {
	EFI_TABLE_HEADER Hdr;
	void *RaiseTPL;
	void *RestoreTPL;
	void *AllocatePages;
	void *FreePages;
	void *GetMemoryMap;
	EFI_STATUS(EFIAPI *AllocatePool)(UINT32 PoolType, UINTN Size, void **Buffer);
	EFI_STATUS(EFIAPI *FreePool)(void *Buffer);
	void *CreateEvent;
	void *SetTimer;
	void *WaitForEvent;
	void *SignalEvent;
	void *CloseEvent;
	void *CheckEvent;
	void *InstallProtocolInterface;
	void *ReinstallProtocolInterface;
	void *UninstallProtocolInterface;
	EFI_STATUS(EFIAPI *HandleProtocol)(EFI_HANDLE Handle, const EFI_GUID *Protocol,
					   void **Interface);
	void *Reserved;
	void *RegisterProtocolNotify;
	void *LocateHandle;
	void *LocateDevicePath;
	void *InstallConfigurationTable;
	EFI_STATUS(EFIAPI *LoadImage)(BOOLEAN BootPolicy, EFI_HANDLE ParentImageHandle,
				      const void *DevicePath, void *SourceBuffer,
				      UINTN SourceSize, EFI_HANDLE *ImageHandle);
	EFI_STATUS(EFIAPI *StartImage)(EFI_HANDLE ImageHandle, UINTN *ExitDataSize,
				       CHAR16 **ExitData);
	void *Exit;
	EFI_STATUS(EFIAPI *UnloadImage)(EFI_HANDLE ImageHandle);
	void *ExitBootServices;
	void *GetNextMonotonicCount;
	void *Stall;
	void *SetWatchdogTimer;
	void *ConnectController;
	void *DisconnectController;
	void *OpenProtocol;
	void *CloseProtocol;
	void *OpenProtocolInformation;
	void *ProtocolsPerHandle;
	void *LocateHandleBuffer;
	void *LocateProtocol;
	void *InstallMultipleProtocolInterfaces;
	void *UninstallMultipleProtocolInterfaces;
	EFI_STATUS(EFIAPI *CalculateCrc32)(const void *Data, UINTN DataSize, UINT32 *Crc32);
} EFI_BOOT_SERVICES;

typedef struct {
	EFI_TABLE_HEADER Hdr;
	CHAR16 *FirmwareVendor;
	UINT32 FirmwareRevision;
	EFI_HANDLE ConsoleInHandle;
	void *ConIn;
	EFI_HANDLE ConsoleOutHandle;
	SIMPLE_TEXT_OUTPUT *ConOut;
	EFI_HANDLE StandardErrorHandle;
	void *StdErr;
	EFI_RUNTIME_SERVICES *RuntimeServices;
	EFI_BOOT_SERVICES *BootServices;
} EFI_SYSTEM_TABLE;

typedef struct {
	UINT32 Revision;
	EFI_HANDLE ParentHandle;
	EFI_SYSTEM_TABLE *SystemTable;
	EFI_HANDLE DeviceHandle;
} EFI_LOADED_IMAGE;

typedef struct EFI_FILE EFI_FILE;
struct EFI_FILE {
	UINT64 Revision;
	EFI_STATUS(EFIAPI *Open)(EFI_FILE *This, EFI_FILE **NewHandle, const CHAR16 *Name,
				 UINT64 OpenMode, UINT64 Attributes);
	EFI_STATUS(EFIAPI *Close)(EFI_FILE *This);
	void *Delete;
	EFI_STATUS(EFIAPI *Read)(EFI_FILE *This, UINTN *BufferSize, void *Buffer);
};

typedef struct {
	UINT64 Revision;
	EFI_STATUS(EFIAPI *OpenVolume)(void *This, EFI_FILE **Root);
} EFI_SIMPLE_FILE_SYSTEM;

/* Offsets from the UEFI specification (2.10), LP64. */
_Static_assert(offsetof(EFI_SYSTEM_TABLE, ConOut) == 0x40, "ConOut");
_Static_assert(offsetof(EFI_SYSTEM_TABLE, RuntimeServices) == 0x58, "RT");
_Static_assert(offsetof(EFI_SYSTEM_TABLE, BootServices) == 0x60, "BS");
_Static_assert(offsetof(EFI_RUNTIME_SERVICES, GetVariable) == 0x48, "GetVariable");
_Static_assert(offsetof(EFI_RUNTIME_SERVICES, SetVariable) == 0x58, "SetVariable");
_Static_assert(offsetof(EFI_BOOT_SERVICES, AllocatePool) == 0x40, "AllocatePool");
_Static_assert(offsetof(EFI_BOOT_SERVICES, FreePool) == 0x48, "FreePool");
_Static_assert(offsetof(EFI_BOOT_SERVICES, HandleProtocol) == 0x98, "HandleProtocol");
_Static_assert(offsetof(EFI_BOOT_SERVICES, LoadImage) == 0xc8, "LoadImage");
_Static_assert(offsetof(EFI_BOOT_SERVICES, StartImage) == 0xd0, "StartImage");
_Static_assert(offsetof(EFI_BOOT_SERVICES, UnloadImage) == 0xe0, "UnloadImage");
_Static_assert(offsetof(EFI_BOOT_SERVICES, CalculateCrc32) == 0x158, "CalculateCrc32");
_Static_assert(offsetof(EFI_LOADED_IMAGE, DeviceHandle) == 0x18, "DeviceHandle");
_Static_assert(offsetof(EFI_FILE, Read) == 0x20, "Read");

static const EFI_GUID GLOBAL_VARIABLE = {
	0x8be4df61, 0x93ca, 0x11d2, {0xaa, 0x0d, 0x00, 0xe0, 0x98, 0x03, 0x2b, 0x8c}};
static const EFI_GUID IMAGE_SECURITY_DATABASE = {
	0xd719b2cb, 0x3d3a, 0x4596, {0xa3, 0xbc, 0xda, 0xd0, 0x0e, 0x67, 0x65, 0x6f}};
static const EFI_GUID LOADED_IMAGE_PROTOCOL = {
	0x5b1b31a1, 0x9562, 0x11d2, {0x8e, 0x3f, 0x00, 0xa0, 0xc9, 0x69, 0x72, 0x3b}};
static const EFI_GUID SIMPLE_FILE_SYSTEM_PROTOCOL = {
	0x964e5b22, 0x6459, 0x11d2, {0x8e, 0x39, 0x00, 0xa0, 0xc9, 0x69, 0x72, 0x3b}};
static const EFI_GUID DEVICE_PATH_PROTOCOL = {
	0x09576e91, 0x6d3f, 0x11d2, {0x8e, 0x39, 0x00, 0xa0, 0xc9, 0x69, 0x72, 0x3b}};

static EFI_HANDLE image_handle;
static EFI_HANDLE device_handle;
static EFI_BOOT_SERVICES *bs;
static EFI_RUNTIME_SERVICES *rt;
static SIMPLE_TEXT_OUTPUT *con;
static EFI_FILE *esp_root;
static UINT8 *var_buf;

static CHAR16 line[256];
static UINTN line_len;

/*
 * The compiler may lower a struct copy or a fill to these calls even in
 * a freestanding build; -fno-tree-loop-distribute-patterns keeps their
 * own loops from becoming calls to themselves.
 */
void *memset(void *dst, int c, UINTN n)
{
	UINT8 *d = dst;

	while (n--)
		*d++ = (UINT8)c;
	return dst;
}

void *memcpy(void *dst, const void *src, UINTN n)
{
	UINT8 *d = dst;
	const UINT8 *s = src;

	while (n--)
		*d++ = *s++;
	return dst;
}

static void put_ascii(const char *s)
{
	while (*s && line_len < sizeof(line) / sizeof(line[0]) - 3)
		line[line_len++] = (CHAR16)(UINT8)*s++;
}

static void put_hex(UINT64 v, int digits)
{
	const char *hex = "0123456789abcdef";
	int i;

	put_ascii("0x");
	for (i = digits - 1; i >= 0 && line_len < sizeof(line) / sizeof(line[0]) - 3; i--)
		line[line_len++] = (CHAR16)hex[(v >> (4 * i)) & 0xf];
}

static void put_dec(UINT64 v)
{
	char buf[24];
	int n = 0;

	do {
		buf[n++] = (char)('0' + v % 10);
		v /= 10;
	} while (v && n < (int)sizeof(buf));
	while (n-- && line_len < sizeof(line) / sizeof(line[0]) - 3)
		line[line_len++] = (CHAR16)buf[n];
}

static void flush_line(void)
{
	line[line_len++] = '\r';
	line[line_len++] = '\n';
	line[line_len] = 0;
	con->OutputString(con, line);
	line_len = 0;
}

static void start_line(const char *kind, const char *tag)
{
	line_len = 0;
	put_ascii("N7PROBE ");
	put_ascii(kind);
	put_ascii(" ");
	put_ascii(tag);
}

static void put_status(EFI_STATUS s)
{
	put_ascii(" status=");
	put_hex(s, 16);
}

static EFI_STATUS read_file(const CHAR16 *path, UINT8 **out, UINTN *size)
{
	EFI_FILE *f = NULL;
	void *buf = NULL;
	UINTN n = FILE_CAP;
	EFI_STATUS s;

	s = esp_root->Open(esp_root, &f, path, EFI_FILE_MODE_READ, 0);
	if (s != EFI_SUCCESS)
		return s;
	s = bs->AllocatePool(EFI_LOADER_DATA, FILE_CAP, &buf);
	if (s != EFI_SUCCESS) {
		f->Close(f);
		return s;
	}
	s = f->Read(f, &n, buf);
	f->Close(f);
	if (s == EFI_SUCCESS && n == FILE_CAP)
		s = EFI_BUFFER_TOO_SMALL; /* refuse a truncated payload */
	if (s != EFI_SUCCESS) {
		bs->FreePool(buf);
		return s;
	}
	*out = buf;
	*size = n;
	return EFI_SUCCESS;
}

static void read_var(const char *phase, const char *tag, const CHAR16 *name,
		     const EFI_GUID *vendor)
{
	UINT32 attr = 0;
	UINT32 crc = 0;
	UINTN size = VAR_CAP;
	EFI_STATUS s;

	s = rt->GetVariable(name, vendor, &attr, &size, var_buf);
	if (s == EFI_SUCCESS)
		bs->CalculateCrc32(var_buf, size, &crc);
	else
		size = 0;
	start_line("READ", phase);
	put_ascii(" ");
	put_ascii(tag);
	put_status(s);
	put_ascii(" attr=");
	put_hex(attr, 8);
	put_ascii(" size=");
	put_dec(size);
	put_ascii(" crc=");
	put_hex(crc, 8);
	flush_line();
}

static void read_all(const char *phase)
{
	read_var(phase, "PK", u"PK", &GLOBAL_VARIABLE);
	read_var(phase, "KEK", u"KEK", &GLOBAL_VARIABLE);
	read_var(phase, "db", u"db", &IMAGE_SECURITY_DATABASE);
	read_var(phase, "dbx", u"dbx", &IMAGE_SECURITY_DATABASE);
}

static void run_row(const char *tag, const CHAR16 *path, const CHAR16 *name,
		    const EFI_GUID *vendor)
{
	UINT8 *buf = NULL;
	UINTN size = 0;
	UINT32 attr;
	EFI_STATUS s;

	s = read_file(path, &buf, &size);
	if (s == EFI_SUCCESS && size < 4) {
		bs->FreePool(buf);
		s = EFI_BUFFER_TOO_SMALL;
	}
	if (s != EFI_SUCCESS) {
		start_line("LOADERR", tag);
		put_status(s);
		flush_line();
		return;
	}
	attr = (UINT32)buf[0] | (UINT32)buf[1] << 8 | (UINT32)buf[2] << 16 |
	       (UINT32)buf[3] << 24;
	s = rt->SetVariable(name, vendor, attr, size - 4, size > 4 ? buf + 4 : NULL);
	start_line("ROW", tag);
	put_ascii(" attr=");
	put_hex(attr, 8);
	put_ascii(" size=");
	put_dec(size - 4);
	put_status(s);
	flush_line();
	bs->FreePool(buf);
}

/*
 * The device path of the probe's own partition plus one file-path
 * node, so a loaded image gets the ESP as its device: systemd-boot finds
 * its entries through that handle.  Nodes are byte-packed, so they are
 * written byte by byte.
 */
static void *file_path(const CHAR16 *path)
{
	UINT8 *base = NULL;
	UINT8 *dp = NULL;
	UINT8 *node;
	UINTN dev_len = 0;
	UINTN path_len = 0;
	UINTN node_len;
	UINTN i;

	if (bs->HandleProtocol(device_handle, &DEVICE_PATH_PROTOCOL, (void **)&base) !=
	    EFI_SUCCESS)
		return NULL;
	for (;;) {
		UINTN len = (UINTN)base[dev_len + 2] | (UINTN)base[dev_len + 3] << 8;

		if (base[dev_len] == 0x7f && base[dev_len + 1] == 0xff)
			break;
		if (len < 4)
			return NULL;
		dev_len += len;
	}
	while (path[path_len])
		path_len++;
	node_len = 4 + 2 * (path_len + 1);
	if (bs->AllocatePool(EFI_LOADER_DATA, dev_len + node_len + 4, (void **)&dp) !=
	    EFI_SUCCESS)
		return NULL;
	memcpy(dp, base, dev_len);
	node = dp + dev_len;
	node[0] = 0x04; /* media device path */
	node[1] = 0x04; /* file path */
	node[2] = (UINT8)(node_len & 0xff);
	node[3] = (UINT8)(node_len >> 8);
	for (i = 0; i <= path_len; i++) {
		node[4 + 2 * i] = (UINT8)(path[i] & 0xff);
		node[5 + 2 * i] = (UINT8)(path[i] >> 8);
	}
	node += node_len;
	node[0] = 0x7f; /* end of the whole device path */
	node[1] = 0xff;
	node[2] = 4;
	node[3] = 0;
	return dp;
}

/* L1: the target is signed by the KEK key alone, so only a db that the
 * S-db row extended with the KEK certificate lets it load.  It is never
 * started. */
static void run_l1(void)
{
	EFI_HANDLE h = NULL;
	void *dp = file_path(u"\\n7\\n7-target.efi");
	EFI_STATUS s;

	if (!dp) {
		start_line("LOADERR", "L1");
		put_status(EFI_NOT_FOUND);
		flush_line();
		return;
	}
	s = bs->LoadImage(0, image_handle, dp, NULL, 0, &h);
	start_line("L1", "n7-target");
	put_status(s);
	flush_line();
	if (h)
		bs->UnloadImage(h);
	bs->FreePool(dp);
}

static EFI_STATUS chain_load(void)
{
	EFI_HANDLE h = NULL;
	void *dp = file_path(u"\\n7\\sdboot.efi");
	EFI_STATUS s = EFI_NOT_FOUND;

	if (dp) {
		s = bs->LoadImage(0, image_handle, dp, NULL, 0, &h);
		if (s == EFI_SUCCESS)
			s = bs->StartImage(h, NULL, NULL);
	}
	/* Reached only if systemd-boot did not load or returned. */
	start_line("CHAIN", "sdboot");
	put_status(s);
	flush_line();
	return s;
}

EFI_STATUS EFIAPI efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *st);

EFI_STATUS EFIAPI efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *st)
{
	EFI_LOADED_IMAGE *li = NULL;
	EFI_SIMPLE_FILE_SYSTEM *fs = NULL;
	EFI_STATUS s;

	image_handle = image;
	bs = st->BootServices;
	rt = st->RuntimeServices;
	con = st->ConOut;

	start_line("BEGIN", "v1");
	flush_line();

	s = bs->HandleProtocol(image, &LOADED_IMAGE_PROTOCOL, (void **)&li);
	if (s == EFI_SUCCESS) {
		device_handle = li->DeviceHandle;
		s = bs->HandleProtocol(device_handle, &SIMPLE_FILE_SYSTEM_PROTOCOL,
				       (void **)&fs);
	}
	if (s == EFI_SUCCESS)
		s = fs->OpenVolume(fs, &esp_root);
	if (s == EFI_SUCCESS)
		s = bs->AllocatePool(EFI_LOADER_DATA, VAR_CAP, (void **)&var_buf);
	if (s != EFI_SUCCESS) {
		start_line("SETUPERR", "esp");
		put_status(s);
		flush_line();
		return s;
	}

	read_all("pre");

	run_row("U-PK", u"\\n7\\U-PK.bin", u"PK", &GLOBAL_VARIABLE);
	run_row("U-KEK", u"\\n7\\U-KEK.bin", u"KEK", &GLOBAL_VARIABLE);
	run_row("U-db", u"\\n7\\U-db.bin", u"db", &IMAGE_SECURITY_DATABASE);
	run_row("W-db", u"\\n7\\W-db.bin", u"db", &IMAGE_SECURITY_DATABASE);
	run_row("X-PK", u"\\n7\\X-PK.bin", u"PK", &GLOBAL_VARIABLE);
	run_row("S-db", u"\\n7\\S-db.bin", u"db", &IMAGE_SECURITY_DATABASE);
	run_row("S-KEK", u"\\n7\\S-KEK.bin", u"KEK", &GLOBAL_VARIABLE);
	run_l1();
	run_row("S-PK", u"\\n7\\S-PK.bin", u"PK", &GLOBAL_VARIABLE);

	read_all("post");

	start_line("END", "v1");
	flush_line();

	return chain_load();
}
