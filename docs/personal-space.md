# Personal space

Personal space is a persistent, password-locked workspace on this computer. It is
not an account or a login for the entire studio. Set its password in **Settings →
Personal space**, or use **Personal space** in the sidebar. Use a unique passphrase
of at least 12 characters. There is no password recovery or reset.

Private projects, styles, references, images, videos, meshes, thumbnails and job
history are separate from the regular workspace. Existing regular projects are
not moved or encrypted. Installed model weights and GPU settings remain shared.
Incognito and personal space cannot be active together.

Use **Lock and leave** to return to regular Settings. A new studio document
(including opening another tab or reloading), leaving the page, 15 minutes
without interaction, or a server restart locks the space. Background polling
does not extend that timeout. Browser tabs share the session cookie and lock;
stale tabs cannot silently submit a private generation to the regular workspace.
The automatic update launcher waits for private sessions to end.

Locking revokes browser access immediately and cancels queued jobs. A running
image may finish and save its result privately before its worker is stopped.
Unlocking waits until that worker and file cleanup have finished. Video/mesh
workers honor their existing cancellation mechanisms. Saved work is retained.

## Storage and downloads

The archive is `data/personal/`. The encrypted catalog contains project names,
prompts, generation settings, original file names and the file index. Each saved
file is an authenticated encrypted blob with an opaque name. SQLite runs in
memory: no plaintext SQL database, journal or WAL is written for this workspace.
Private composer and workshop drafts are not written to browser local storage.

Downloads decrypt on demand into ordinary PNG, video, audio, mesh or ZIP files.
They leave the protection of the vault and can include generation metadata such
as prompts. Keep those exports somewhere appropriate. API and asset responses
use `Cache-Control: no-store`.

Back up the **entire** `data/personal/` directory while locked and after any job
has finished. The wrapped key and encrypted catalog are both essential. Keep the
password separately. Changing the password rewraps the data key without rewriting
large media files. An older backup of the wrapped key still uses its old password.

## Cryptography and boundaries

- A random 256-bit data key encrypts the catalog and blobs with AES-256-GCM.
  Each write uses a fresh random 96-bit nonce and a full 128-bit authentication
  tag. Associated data binds each ciphertext to its file name and format version.
  Authentication is checked before a download or native input is exposed.
- Password wrapping uses AES-GCM and scrypt with a random 128-bit salt,
  `N=2^17`, `r=8`, `p=1` (128 MiB). The password and unwrapped key are never saved
  by the app. Failed unlocks are rate limited after five attempts for one minute.
- The live key exists only in the server process. Server restart invalidates all
  sessions. The browser receives an opaque HttpOnly, SameSite=Strict session cookie,
  never the encryption key. Workspace headers reject stale cross-space requests;
  origin and trusted-host checks remain enabled.
- The archive conceals file contents and names, not total size, file count or
  modification times. It does not conceal which model weights are installed.

Native GPU tools need plaintext inputs, outputs and logs while working. They use
isolated, marked directories under `data/temporary/`. Completed media is encrypted
before entering history. Inputs and native output folders are cleaned after their
operation. Image workers and the H3 resident worker keep compatible model caches
between generations while the space is open, unless **Unload after each job** is
enabled. H3 can still evict individual components when memory is needed. Runtime logs and
caches remain in the session's scratch directory until it closes. Locking,
expiration and switching workspaces release the session's worker; closing the
session removes its scratch directory. Lock cleanup waits for in-flight requests
and workers. After a crash, marked scratch
directories are removed on the next start. Cleanup failures are surfaced rather
than represented as successful erasure.

This is **not secure disk erasure**, full-disk encryption, a process sandbox or
protection against malware/admin access to an unlocked computer. Operating-system
swap, crash dumps, disk recovery and user-created exports are outside its control.
Use full-disk encryption if those threats matter. Python cannot promise reliable
zeroization of every historical memory copy. Third-party adapters execute trusted
local code and must follow the runtime storage contract; an adapter writing to its
own persistent directories can defeat these protections. LAN access is intended
for trusted home networks only. The regular workspace has no login, and HTTP does
not encrypt passwords, session cookies or media in transit. Personal-space disk
encryption is not transport encryption. Never forward the studio port to the
internet; set `ATELIER_LOCAL_ONLY=1` before starting to restrict it to this computer.

Implementation references: [cryptography authenticated encryption](https://cryptography.io/en/stable/hazmat/primitives/symmetric-encryption/)
and [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).

## Integration

`atelier/vault.py` implements the archive. `SessionRouter` chooses ordinary,
temporary or encrypted storage. Asset readers/writers use `Store.read_file`,
`write_file`, `open_media` and `write_image`; native tools use `input_path` within
`file_scope`, and `output_folder` followed by `seal_folder`. Do not bypass these
methods for persistent private assets.

Endpoints: `GET /api/personal`, `POST /api/personal/setup`, `/unlock`, `/lock`,
`/touch`, and `/password`. Setup accepts `password`; password changes also require
`current_password`. Never log these request bodies. Test only with synthetic
passwords and isolated data roots (`tests/test_vault.py`).
