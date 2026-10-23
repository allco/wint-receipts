# Wint API reference

Reference for the public Wint (wint.se) REST API, generated from the live OpenAPI spec
on 2026-10-21 and annotated by hand. The hand-written guide comes first. The full
endpoint and schema listing below it is generated from the spec.

## Sources

| What | URL |
|---|---|
| Swagger UI | https://api.wint.se/index.html |
| Public spec, "Wint API" (OpenAPI 3.0.4) — **this document** | https://api.wint.se/swagger/v1/swagger.json |
| Internal spec (web-app-only endpoints) | https://api.wint.se/swagger/Internal/swagger.json |
| Full spec (public + internal, 568 paths) | https://api.wint.se/swagger/Full/swagger.json |
| Full spec, camelCase property names | https://api.wint.se/swagger/FullCamel/swagger.json |

To regenerate the listing, download the v1 spec and rerun the generator (it lives in the
session scratchpad and is not part of this repo). The spec has 233 paths, 312 operations
and 409 schemas.

## Basics

- **Base URL**: `https://api.wint.se`. Every route sits under `/api/...`.
- **Server**: ASP.NET on IIS (Swashbuckle-generated spec).
- **Format**: JSON. Requests accept `application/json`, `text/json`,
  `application/*+json` and `application/json-patch+json`. Responses are offered as `application/json`,
  `text/json` or `text/plain`, so send `Accept: application/json`.
- **Property casing**: PascalCase (`ReceiptCategoryId`, `Amount`, ...). The `FullCamel` spec
  exists for camelCase clients, but this reference uses the v1 spec's PascalCase names.
- **Enums**: the spec types them as strings, but **responses send integers** (verified:
  `"State": 1` = `Booked`, `"PaymentMethodType": 2` = `OwnExpense`). Map them with the
  `N - Name` table in each enum's schema entry. Note that the values aren't always contiguous
  (`ReceiptStateApiModel` has `100 - Purchased`, `101 - Paid`).
- **Dates** use `string(date-time)`, ISO 8601.
- **Binary data** in JSON (`format: byte`, e.g. `ReceiptAttachment.Data`) is base64.
- **Rate limit**: 1000 requests per minute, reported in response headers:
  `x-rate-limit-limit: 1m`, `x-rate-limit-remaining`, `x-rate-limit-reset` (UTC timestamp).
  Expect `429` when you go over.

## Authentication

The spec declares **no** `securitySchemes`. A request without credentials returns:

```
HTTP/2 401
www-authenticate: Basic realm="Wint.se", charset="UTF-8"
```

So the API uses **HTTP Basic auth**. There are three ways to get credentials:

1. **Email + password login** — `POST /api/Auth` with
   `{"Mail": "...", "Password": "..."}` returns a
   [`UserLoginInfo`](#schema-userlogininfo). That object has `Key` (uuid), a `State`
   ([`LoginState`](#schema-loginstate): `Success`, `WrongUsernameOrPassword`, `AccountLocked`,
   `NoCompanies`, `ForceLoginWithBankId`, ...), the user's `CompanyNames`, `PaymentMethods`
   and `AuthTokens`.
2. **JWT** — `POST /api/Auth/jwt` (same body) returns `UserLoginInfo` with
   `AuthTokens { AccessToken, RefreshToken }`. To renew, call `POST /api/Auth/refresh` with the
   refresh token as a JSON string body. Use the access token as `Authorization: Bearer <AccessToken>`
   (this is the usual convention; the spec doesn't document it).
3. **API key ("Custom app")** — in the Wint web app, go to *Settings → Integrations* and create a
   custom app (category `OwnApp`). Behind the scenes this calls the internal
   `POST /api/Settings/Integration/CustomApp` and `GenerateCustomAppKey`. A
   `CustomApp` (internal spec) has a `UserName` and a uuid `APIKey`. **This is the recommended
   route for a script or integration.** Verified on 2026-10-21: Basic auth as
   `<company id>:<API key uuid>` works. The username is the numeric company
   id that `GET /api/Auth` returns as `Id`.

Accounts that must log in with BankID (`State = ForceLoginWithBankId`) can't use
email/password login. They need an API key, or the BankID flow at `/api/BankIdAuth/*`
(internal spec).

**Company context.** A user can belong to several companies. `GET /api/Auth` returns the
[`Company`](#schema-company) the request is authenticated against. It includes permission flags
(`ReceiptCreator`, `ReceiptViewer`, `SupplierInvoiceCreator`, ...), the available
`ReceiptCategories`, `ReceiptDimensions`, `ReceiptPaymentMethods`, `FinancialYears`, `NoVat`,
`LockDate`, and more. To switch company, use the internal `POST /api/CompanyAuth`
`{"CompanyId": n}`, which returns a new key (uuid). An API key is already scoped to one company.

**Revoking keys**: `DELETE /api/auth/key` revokes the key used on that request.
`DELETE /api/auth/keys` revokes all of the user's keys.

In this repo the credentials are in `./.CREDENTIALS` (git-ignore it): `WINT_USER` (company id) and
`WINT_TOKEN` (API key).

```bash
# Read-only smoke test (verified: returns 200 + the Company object)
. ./.CREDENTIALS
curl -sS -u "$WINT_USER:$WINT_TOKEN" -H 'Accept: application/json' \
  https://api.wint.se/api/Auth | jq '{Id, Name, Org, ReceiptCreator}'
```

> Still unverified: how to use the `UserLoginInfo.Key` returned by `POST /api/Auth` (email login),
> and the JWT bearer flow. Neither was tested, because both need a write-style login call.

> **Project rule: read-only.** Against the live account, use only `GET`. Every `POST`/`PUT`/`PATCH`/`DELETE`,
> including logins and key revocation, needs an explicit go-ahead first.

## Common conventions

### List endpoints and paging

List `GET`s take a filter object as **query parameters** and return
`Wint.Utils.WebApi.ListResponseOf_<T>`:

```json
{ "Items": [ ... ], "Page": 1, "NumPerPage": 50, "TotalItems": 123,
  "TotalItemsWithOutFilter": 456, "SummaryItem": { ... } }
```

The usual paging and sort parameters are `Page`, `NumPerPage`, `OrderByProperty`,
`OrderByDescending`, `ThenByProperty`, `ThenByDescending`, `IsAutoPaginating` and
`IncludeSummary` (the last one fills `SummaryItem` with totals). To pass an array parameter,
repeat the key: `States=Booked&States=Paid`.

**`Page` starts at 0** (verified 2026-10-21): no `Page` or `Page=0` returns the first page, and
`Page=1` the second. `NumPerPage=500` is accepted. Keep fetching until `Items` is shorter than
`NumPerPage`, or until you've collected `TotalItems`.

**Receipt persons** (verified): `GET /api/Receipt/AllReceiptPersons` returns the whole address book.
`GET /api/Receipt/CommonReceiptPersons` returns the 20 people used most often on receipts, most frequent
first. Despite the summary, it is not limited to the last six months. Persons copied onto a receipt get
a new `Id` each time, so match people across receipts by `Name`, not `Id`.

**Representation participants go in `Persons`** (`ReceiptPost.Persons`, "People the receipt concerns",
items `{Id, Name, Company}`). Verified from history: 497 of 500 receipts in the Representation and
Personalrepresentation categories had their participants there. The account holder usually appears
too, but isn't in the address book, so Wint may add them itself. Creating receipts with `Persons` hasn't
been tested yet.

**The representation reason goes in `Intent`** (`ReceiptPost.Intent`, undocumented in the spec).
Verified from history: 195 of 200 representation receipts had `Intent` = "collaboration discussion";
`Comment` was empty.

### Create / update return ids

`POST` (create) and `PUT /{id}` (update) usually return the entity id as a bare `integer`
(or `uuid`), not the full object. Fetch the object with `GET /{id}` afterwards if you need it.

### Client capabilities header

Some endpoints change behaviour based on `X-Wint-Capabilities` (a comma-separated list). The
documented capability is `ReceiptPaymentMethodNullability`. **Without it, the API hides receipts
whose `PaymentMethodId` is null**: `GET /api/Receipt/{id}` returns 404 and list results leave them
out. Send it whenever you list receipts:

```
X-Wint-Capabilities: ReceiptPaymentMethodNullability
```

## Creating a receipt: what a real upload showed (2026-10-23)

One receipt was created for real (`POST /api/Receipt` → `3026953`, 660 SEK Representation) and read back:

- **The response** is the new receipt id as a bare integer. A ~5.7 MB JSON body was accepted.
- **State** right after creation is `0` (*Received*), so **no `Sign` call is needed**: like the receipts made
  in Wint's own app, it goes on to booking by itself.
- **`Attachments`** with base64 `Data` works; `Images` isn't needed. A JPEG attachment
  (`image/jpeg`, receipt 3027387) is stored and served back unchanged. Wint keeps the file as sent
  (downloaded back byte for byte). An image-only PDF page shows in Wint's web app but **blank in Wint's
  mobile app**, so upload **JPEG** (`image/jpeg`) images instead, one per page.
- **`Persons`** is accepted, including the account holder with `Id: 0`. Wint copies every participant
  onto the receipt with new ids (here 1813614, 1813615).
- **`Intent`** is stored as sent.
- **`ClientId`**: `GET /api/Receipt?ClientId=…` finds the receipt, although `GET /api/Receipt/{id}` shows
  `ClientId: null`. So `ClientId` works as a retry/idempotency key.
- **Duplicates:** there's no delete. `POST /api/Receipt/Cancel/{id}` leaves the receipt visible as
  *Canceled* (state 2). So check before creating: `ClientId` first, then same date + amount
  (`AmountFrom`/`AmountTo`).

## Receipts (kvitton) — guide

Receipts are the expense receipts employees submit for bookkeeping and (for own expenses)
payout. Relevant endpoints: [`Receipt`](#tag-receipt), plus [`CostForwarding`](#tag-costforwarding),
[`Dimension`](#tag-dimension) / [`DimensionTypes`](#tag-dimensiontypes) (`/Receipts`
variants), and the company info from `GET /api/Auth`.

### Reference data to load first

| Need | Where |
|---|---|
| Receipt categories (`ReceiptCategoryId`) | `GET /api/Auth` → `Company.ReceiptCategories[]` (`Id`, `Name`, `CategoryType`) |
| Payment methods (`PaymentMethodId`) | `GET /api/Auth` → `Company.ReceiptPaymentMethods` (map personId → methods), or `UserLoginInfo.PaymentMethods` |
| Dimensions (cost centre / project tags) | `GET /api/Dimension/Receipts`, `GET /api/DimensionTypes/Receipts`, `GET /api/Receipt/DimensionSuggestions` |
| Can I be paid out? | `GET /api/Receipt/CanReceivePayouts` |
| People in the address book (for `Persons`, e.g. representation) | `GET /api/Receipt/AllReceiptPersons`, `CommonReceiptPersons`, `POST AddReceiptPerson` |

[`ReceiptPaymentMethodType`](#schema-receiptpaymentmethodtype) values: `BankCard`, `CreditCard`,
`OwnExpense` (paid privately, so it is paid back), `Cash`, `Settlement`, `WintCard`,
`MissingDocument`.

### Create a receipt

`POST /api/Receipt`, body [`ReceiptPost`](#schema-receiptpost). Returns the new receipt id
(`int32`).

```json
{
  "ClientId": "8f6c1c1e-6a8e-4b8a-9a55-1d2f0f5d7c11",
  "DateTime": "2026-10-20T12:34:00Z",
  "Amount": 249.00,
  "Currency": "SEK",
  "SupplierName": "Clas Ohlson",
  "Comment": "Cables for the office",
  "ReceiptCategoryId": 12,
  "PaymentMethodId": 345,
  "Dimensions": [],
  "Attachments": [
    { "FileName": "receipt.jpg", "ContentType": "image/jpeg", "Data": "<base64>" }
  ]
}
```

- `ClientId` (uuid) is generated by the client. You can filter on it later
  (`GET /api/Receipt?ClientId=...`), which makes it the idempotency / dedup handle for uploads.
- The image goes in `Attachments[]` (`ReceiptAttachment`: base64 `Data`, `FileName`,
  `ContentType`). There is also a legacy `Images: string[]` with no description in the spec,
  probably base64 strings too. Prefer `Attachments`.
- `DimensionList: [{DimensionId, Amount}]` splits the amount across dimensions (the newer
  structure). `Dimensions: uuid[]` is the plain tag list.
- `Persons[]` lists the people the receipt concerns, e.g. guests for representation.
- `IsOtherPaymentMethod` + `OtherPaymentMethodExplanation` is for the "Other" payment method.
- `PUT /api/Receipt/HandleDocumentDraft` `{DocumentDraftId, ReceiptId}` links an uploaded
  document draft to a receipt.

### Lifecycle

[`ReceiptStateApiModel`](#schema-receiptstateapimodel): `Draft`, `Received`, `WaitingAcceptance`,
`Investigation`, `SentBackToCustomer`, `SentBackFromReceiptAdmin`, `PaymentSign`, `Booked`,
`Purchased`, `Paid`, `Stopped`, `PayoutRescheduled`, `Canceled`.

| Action | Endpoint |
|---|---|
| Update | `PUT /api/Receipt/{id}` ([`ReceiptPut`](#schema-receiptput)) |
| Sign (submit / approve) | `POST /api/Receipt/Sign/{id}` |
| Update + sign in one call | `POST /api/Receipt/UpdateAndSign/{id}` |
| Send back to owner | `POST /api/Receipt/SendBack/{id}` ([`ReceiptSendBackData`](#schema-receiptsendbackdata)) |
| Cancel | `POST /api/Receipt/Cancel/{id}` |
| Remove one image | `DELETE /api/Receipt/{receiptId}/Images/{imageId}` |
| State history | `GET /api/Receipt/StateLogs/{id}` |
| Booked vouchers | `GET /api/Receipt/Transactions/{id}` |
| Possible duplicates | `GET /api/Receipt/SimilarAsync/{id}` |
| Download attachment(s) | `GET /api/Receipt/{receiptId}/Attachments/{attachmentId}`, `GET /api/Receipt/GetPdfAsync/{id}` (PDF) |
| Mark to re-invoice a customer | `PUT /api/CostForwarding/receipt/{receiptId}` |

### Query receipts

`GET /api/Receipt` takes filters such as `State`/`States`, `CreatedFromDate`/`CreatedToDate`,
`AmountFrom`/`AmountTo`, `Currency`, `PaymentState` (`Unpaid`/`Paid`), `LastUpdated` (for
incremental sync), `ClientId`, `Dimensions`, `SerialNumberFrom`/`To`, `PaymentMethods`,
`PaymentMethodTypes`, plus paging. Send the `X-Wint-Capabilities` header (see above).

```bash
curl -sS -u "$WINT_USER:$WINT_API_KEY" \
  -H 'Accept: application/json' \
  -H 'X-Wint-Capabilities: ReceiptPaymentMethodNullability' \
  'https://api.wint.se/api/Receipt?States=Received&States=Booked&Page=1&NumPerPage=50&OrderByProperty=DateTime&OrderByDescending=true'
```

## Other areas at a glance

| Tag | What it covers |
|---|---|
| Invoice, Customer, Article, Unit, InvoicePaymentOption, Reference, Series | Customer invoicing (kundfakturor), quotations, reminders, customers and articles |
| SelfInvoice | Self-invoices |
| AgingIncomingInvoice | Supplier-invoice aging (leverantörsreskontra) |
| Voucher, VoucherImages, Transaction, Account, Document | Bookkeeping: vouchers (verifikationer), their images, transactions, chart of accounts, SIE file import |
| MissingDocument | Bank transactions missing a receipt (saknade underlag) |
| FinancialReports, MonthlyReports, VatReports, Declaration, DimensionsReport, Report, RevenueReporting, BankBalance | Reports and balances |
| CashReconciliation | Daily cash (dagskassa) |
| Employees, SalaryDrafts, SalaryDeviation, WintSalaryDeviation, SalaryImport, TimeReport | Payroll and time reporting |
| Dimension, DimensionTypes | Cost centres / projects |
| CostForwarding | Re-invoicing costs to customers |
| Support, SupportAgent, Survey, ProfileRoutine, Search | Support tickets with the Wint accountants, misc. |

---

## Endpoint index

- [Account](#tag-account) — 4 ops
- [AgingIncomingInvoice](#tag-agingincominginvoice) — 1 ops
- [Article](#tag-article) — 10 ops
- [Auth](#tag-auth) — 6 ops
- [BankBalance](#tag-bankbalance) — 3 ops
- [CashReconciliation](#tag-cashreconciliation) — 10 ops
- [CostForwarding](#tag-costforwarding) — 6 ops
- [Currency](#tag-currency) — 1 ops
- [Customer](#tag-customer) — 16 ops
- [Declaration](#tag-declaration) — 1 ops
- [Dimension](#tag-dimension) — 7 ops
- [DimensionTypes](#tag-dimensiontypes) — 4 ops
- [DimensionsReport](#tag-dimensionsreport) — 1 ops
- [Document](#tag-document) — 1 ops
- [Employees](#tag-employees) — 5 ops
- [FinancialReports](#tag-financialreports) — 9 ops
- [Invoice](#tag-invoice) — 47 ops
- [InvoicePaymentOption](#tag-invoicepaymentoption) — 1 ops
- [MissingDocument](#tag-missingdocument) — 3 ops
- [MonthlyReports](#tag-monthlyreports) — 9 ops
- [ProfileRoutine](#tag-profileroutine) — 1 ops
- [Receipt](#tag-receipt) — 23 ops
- [Reference](#tag-reference) — 8 ops
- [Report](#tag-report) — 1 ops
- [RevenueReporting](#tag-revenuereporting) — 9 ops
- [SalaryDeviation](#tag-salarydeviation) — 9 ops
- [SalaryDrafts](#tag-salarydrafts) — 9 ops
- [SalaryImport](#tag-salaryimport) — 1 ops
- [Search](#tag-search) — 1 ops
- [SelfInvoice](#tag-selfinvoice) — 7 ops
- [Series](#tag-series) — 1 ops
- [Support](#tag-support) — 20 ops
- [SupportAgent](#tag-supportagent) — 4 ops
- [Survey](#tag-survey) — 9 ops
- [TimeReport](#tag-timereport) — 3 ops
- [Transaction](#tag-transaction) — 3 ops
- [Unit](#tag-unit) — 4 ops
- [UserApiKey](#tag-userapikey) — 2 ops
- [VatReports](#tag-vatreports) — 3 ops
- [Voucher](#tag-voucher) — 4 ops
- [VoucherImages](#tag-voucherimages) — 4 ops
- [WintSalaryDeviation](#tag-wintsalarydeviation) — 8 ops

## Endpoints

<a id="tag-account"></a>
### Account

#### `GET /api/Account`

Filter account

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Name` | query | `string` |  | Name to filter on |
| `NumberList` | query | `integer(int32)`[] |  | List of account numbers to include |
| `ExcludedAccountNumbers` | query | `integer(int32)`[] |  | List of accounts to exclude |
| `ExactNumber` | query | `integer(int32)` |  | Account number |
| `StartNumber` | query | `integer(int32)` |  | Start of account number |
| `EndNumber` | query | `integer(int32)` |  | End of account number |
| `Active` | query | `boolean` |  | Include only active accounts |
| `Modified` | query | `string(date-time)` |  | Include accounts modified since this date |
| `ExactAccounts` | query | `string(uuid)`[] |  | Account Ids |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Accounting.Account`](#schema-wint-utils-webapi-listresponseof-accounting-account)

#### `GET /api/Account/AccountBalance/{account}`

Get account balance

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `account` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Accounting.AccountBalance`](#schema-accounting-accountbalance)

#### `GET /api/Account/AccountingDoneUntil`

Get accounting completed until: year month

**Responses**: `200` `string(date-time)`

#### `GET /api/Account/RevenueAccounts`

The revenue accounts selectable on articles, per VAT rate: the company's Heart-configured intervals intersected with active accounts. Uses article roles (the plain account filter endpoint requires Reports/Admin, which invoice users lack).

**Responses**: `200` [`Accounting.RevenueAccountsResponse`](#schema-accounting-revenueaccountsresponse)

<a id="tag-agingincominginvoice"></a>
### AgingIncomingInvoice

#### `PUT /api/AgingIncomingInvoice`

**Body**: [`AgingIncomingInvoices.AgingIncomingInvoiceUpdateInfo`](#schema-agingincominginvoices-agingincominginvoiceupdateinfo)

**Responses**: `200` OK

<a id="tag-article"></a>
### Article

#### `GET /api/Article`

Returns a list of articles based on given article filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `UnitId` | query | `integer(int32)` |  | Article unit id |
| `UpdatedAfter` | query | `string(date-time)` |  | Articles updated after given date |
| `Inactive` | query | `boolean` |  | Whether the article is active or not. |
| `Name` | query | `string` |  | Article name contains this text. |
| `EuVatProductType` | query | [`EuVatProductType`](#schema-euvatproducttype)[] |  | Article has one of the EU Vat types. |
| `UnitPriceFrom` | query | `number(double)` |  | Article has a unit price greater than or equal to this. |
| `UnitPriceTo` | query | `number(double)` |  | Article has a unit price less than or equal to this |
| `TotalAmountForLastYearlyPeriodFrom` | query | `number(double)` |  | Article's total sales within last 12 months greater than or equal to this. |
| `TotalAmountForLastYearlyPeriodTo` | query | `number(double)` |  | Article's total sales within last 12 months less than or equal to this. |
| `TotalQuantityForLastYearlyPeriodFrom` | query | `number(double)` |  | Article's total quatities sold within last 12 months greater than or equal to this |
| `TotalQuantityForLastYearlyPeriodTo` | query | `number(double)` |  | Article's total quatities sold within last 12 months less than or equal to this |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Article`](#schema-wint-utils-webapi-listresponseof-article)

#### `POST /api/Article`

Creates an article based on given article data

**Body**: [`ArticlePost`](#schema-articlepost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Article/{id}`

Returns a article based on given article id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Article`](#schema-article)

#### `PUT /api/Article/{id}`

Updates an article based on given article id and data

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`ArticlePut`](#schema-articleput)

**Responses**: `200` `integer(int32)`

#### `DELETE /api/Article/{id}`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `POST /api/Article/Activate/{id}`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `POST /api/Article/Deactivate/{id}`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `GET /api/Article/SearchByName`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `searchName` | query | `string` |  |  |

**Responses**: `200` [`ArticleSearchResponse`](#schema-articlesearchresponse)[]

#### `GET /api/Article/Common`

**Responses**: `200` [`ArticleSearchResponse`](#schema-articlesearchresponse)[]

#### `POST /api/Article/ImportArticles`

**Body**: [`ArticleImportRequest`](#schema-articleimportrequest)

**Responses**: `200` OK

<a id="tag-auth"></a>
### Auth

#### `GET /api/Auth`

Information about the current authenticated company

**Responses**: `200` [`Company`](#schema-company)

#### `POST /api/Auth`

**Body**: [`AuthPost`](#schema-authpost)

**Responses**: `200` [`UserLoginInfo`](#schema-userlogininfo)

#### `POST /api/Auth/jwt`

**Body**: [`AuthPost`](#schema-authpost)

**Responses**: `200` [`UserLoginInfo`](#schema-userlogininfo)

#### `POST /api/Auth/refresh`

**Body**: `string`

**Responses**: `200` [`UserLoginInfo`](#schema-userlogininfo)

#### `POST /api/Auth/ForgotPassword`

**Body**: [`ForgotPassword`](#schema-forgotpassword)

**Responses**: `200` OK

#### `POST /api/Auth/ResetPassword`

**Body**: [`ResetPassword`](#schema-resetpassword)

**Responses**: `200` OK

<a id="tag-bankbalance"></a>
### BankBalance

#### `GET /api/BankBalance/dashboard`

Get the bank balances to show on the dashboard.

One entry per bank account with a live bank connection — a camt statement feed or BankService — that the company has chosen to show. Returns an empty list when the widget is not activated for the company, when no account has a live connection, or when the user lacks the reports permission.

**Responses**: `200` [`BankBalance`](#schema-bankbalance)[]

#### `GET /api/BankBalance/settings`

Get every account the company can show or hide in the widget.

Same data as the dashboard endpoint but including accounts the company has hidden, so the settings screen can offer a toggle per account.

**Responses**: `200` [`BankBalance`](#schema-bankbalance)[]

#### `PUT /api/BankBalance/settings`

Change which accounts appear in the widget.

**Body**: [`BankBalanceVisibilityPut`](#schema-bankbalancevisibilityput)[]

**Responses**: `200` successful operation; `400` An account id the company does not have — the client should reload; `403` The widget is not activated, or the caller may not change it

<a id="tag-cashreconciliation"></a>
### CashReconciliation

#### `GET /api/CashReconciliation/template`

Get cash reconciliation template.

Get the daily cash template for a company if daily cash enabled.

**Responses**: `200` [`CashReconciliationTemplate`](#schema-cashreconciliationtemplate); `400` Daily cash is disabled for the logged in company; `403` No permission

#### `GET /api/CashReconciliation/{id}`

Get cash reconciliation instance.

Get a specific daily cash instance for the given id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Unique ID for the daily cash instance. |

**Responses**: `200` [`CashReconciliationInstance`](#schema-cashreconciliationinstance); `400` Invalid information; `403` No permission

#### `PUT /api/CashReconciliation/{id}`

Update cash reconciliation instance.

Update an existing daily cash instance with given data.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Unique ID for a daily cash instance. |

**Body**: [`CashReconciliationInstanceDto`](#schema-cashreconciliationinstancedto)

**Responses**: `200` `integer(int32)`; `400` Invalid information; `403` No permission

#### `DELETE /api/CashReconciliation/{id}`

Delete cash reconciliation instance.

Delete an existing daily cash instance.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the daily cash instance to be deleted. |

**Responses**: `200` successful operation; `400` Invalid information; `403` No permission

#### `GET /api/CashReconciliation/{id}/attachment/{attachmentId}`

Get cash reconciliation instance attachment.

Get the attachment associated with a daily cash instance.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Unique ID for a daily cash instance. |
| `attachmentId` | path | `string` | yes | Unique ID for a specific attachment. If not provided, the default attachment will be returned. |

**Responses**: `200` [`CashReconciliationAttachment`](#schema-cashreconciliationattachment); `400` Invalid information; `403` No permission

#### `PUT /api/CashReconciliation/{id}/attachment`

Update cash reconciliation instance attachment.

Update the attachment associated with a daily cash instance.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Unique ID for a daily cash instance. |

**Body**: [`CashReconciliationAttachment`](#schema-cashreconciliationattachment)

**Responses**: `200` `integer(int32)`; `400` Invalid information; `403` No permission

#### `GET /api/CashReconciliation`

Get cash reconciliation instance list.

Get all daily cash instances based on the filter.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `IncludeAll` | query | `boolean` |  | Set flag to get company's all daily cash entries or logged in user's entries |
| `FromDate` | query | `string(date-time)` |  | Include daily cash entries created from this date. |
| `ToDate` | query | `string(date-time)` |  | Include daily cash entries created to this date. |
| `MaxSalesAmount` | query | `number(double)` |  | Include daily cash entries with sales less than or equal this. |
| `MinSalesAmount` | query | `number(double)` |  | Include daily cash entries with sales greater than or equal this. |
| `MaxDifference` | query | `number(double)` |  | Include daily cash entries with difference less than or equal this. |
| `MinDifference` | query | `number(double)` |  | Include daily cash entries with difference greater than or equal this. |
| `OwnerIds` | query | `integer(int32)`[] |  | Include daily cash entries with these owners. |
| `DimensionIds` | query | `string(uuid)`[] |  | Include daily cash entries with these dimensions. |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_CashReconciliationInstanceDescriptor`](#schema-wint-utils-webapi-listresponseof-cashreconciliationinstancedescriptor); `403` No permission

#### `POST /api/CashReconciliation`

Create new daily cash instance for given data.

Create new daily cash instance for given data. Use TemplateItemId instead of Account number if your template has duplicate accounts.

**Body**: [`CashReconciliationInstanceDto`](#schema-cashreconciliationinstancedto)

**Responses**: `200` `integer(int32)`; `400` Invalid information; `403` No permission

#### `GET /api/CashReconciliation/{id}/StateLogs`

Returns a list of state logs related to given daily cash instance

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Daily cash id |

**Responses**: `200` [`EntityStateLog`](#schema-entitystatelog)[]

#### `GET /api/CashReconciliation/{id}/Transactions`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Accounting.SimplifiedVoucher`](#schema-accounting-simplifiedvoucher)[]

<a id="tag-costforwarding"></a>
### CostForwarding

#### `GET /api/CostForwarding/forwardable`

Costs waiting to be forwarded to a customer, oldest first, with the net amount each invoice row is built from. Count and total for the reminder come from this same list.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `customerId` | query | `integer(int32)` | yes |  |

**Responses**: `200` [`ForwardableCost`](#schema-forwardablecost)[]; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `GET /api/CostForwarding/receipt/{receiptId}`

The forwarding marking on a receipt. 204 when the receipt is not marked.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `receiptId` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`CostForwarding`](#schema-costforwarding); `204` No Content

#### `PUT /api/CostForwarding/receipt/{receiptId}`

Mark a receipt for forwarding to a customer, or remove the marking with a null CustomerId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `receiptId` | path | `integer(int32)` | yes |  |

**Body**: [`CostForwardingPut`](#schema-costforwardingput)

**Responses**: `200` OK; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `409` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `GET /api/CostForwarding/incominginvoice/{incomingInvoiceId}`

The forwarding marking on a supplier invoice. 204 when the invoice is not marked.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `incomingInvoiceId` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`CostForwarding`](#schema-costforwarding); `204` No Content

#### `PUT /api/CostForwarding/incominginvoice/{incomingInvoiceId}`

Mark a supplier invoice for forwarding to a customer, or remove the marking with a null CustomerId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `incomingInvoiceId` | path | `integer(int32)` | yes |  |

**Body**: [`CostForwardingPut`](#schema-costforwardingput)

**Responses**: `200` OK; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `409` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `POST /api/CostForwarding/{id}/release`

Make a forwarded cost available again, whatever the state of the invoice it is on.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK; `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `409` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

<a id="tag-currency"></a>
### Currency

#### `GET /api/Currency/{currency}`

Get currency exchange between SEK and other currency

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `currency` | path | `string` | yes |  |
| `date` | query | `string` |  |  |

**Responses**: `200` `number(double)`

<a id="tag-customer"></a>
### Customer

#### `GET /api/Customer`

Returns a list of customers based on given customer filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `UpdatedAfter` | query | `string(date-time)` |  | Customers updated after given date |
| `OrgNumber` | query | `string` |  | Customers orgnumber |
| `Name` | query | `string` |  | Customers name |
| `VatNumber` | query | `string` |  | The VAT-number of the customer. The string is case-insensitive. |
| `GlnNumber` | query | `string` |  | The GLN-number of the customer. The string is case-insensitive. |
| `Inactive` | query | `boolean` |  | Whether the customer is active or not. |
| `RatingFrom` | query | `integer(int32)` |  | Customer Rating From |
| `RatingTo` | query | `integer(int32)` |  | Customer Rating To |
| `InvoiceDateFrom` | query | `string(date-time)` |  | Get summary of invoices with invoice date greater than this date |
| `InvoiceDateTo` | query | `string(date-time)` |  | Get summary of invoices with invoice date less than this date |
| `NumOfInvoicesFrom` | query | `integer(int32)` |  | Include customers with number of invoices greater than this |
| `NumOfInvoicesTo` | query | `integer(int32)` |  | Include customers with number of invoices less than this |
| `NumOfRecurringInvoicesFrom` | query | `integer(int32)` |  | Include customers with number of recurring invoices greater than this |
| `NumOfRecurringInvoicesTo` | query | `integer(int32)` |  | Include customers with number of recurring invoices less than this |
| `InvoicedAmountFrom` | query | `integer(int32)` |  | Include customers with total invoiced amount greater than this |
| `InvoicedAmountTo` | query | `integer(int32)` |  | Include customers with total invoiced amount less than this |
| `UnpaidAmountFrom` | query | `integer(int32)` |  | Include customers with total unpaid amount greater than this |
| `UnpaidAmountTo` | query | `integer(int32)` |  | Include customers with total unpaid amount less than this |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Customer`](#schema-wint-utils-webapi-listresponseof-customer)

#### `POST /api/Customer`

Creates a customer based on given customer data

**Body**: [`CustomerPost`](#schema-customerpost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Customer/{id}`

Returns a customer based on given customer id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Customer`](#schema-customer)

#### `PUT /api/Customer/{id}`

Updates a customer based on given customer id and data

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`CustomerPut`](#schema-customerput)

**Responses**: `200` `integer(int32)`; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `409` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `GET /api/Customer/SearchByName`

Return list of invoice customers based on searchString

For search string, you can use the format of "Name (Organization number)"

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `searchString` | query | `string` |  |  |

**Responses**: `200` [`CustomerSearchResponse`](#schema-customersearchresponse)[]

#### `GET /api/Customer/SearchByOrgNr`

Return list of invoice customers based on searchString

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `searchString` | query | `string` |  | A substring of an organization number |

**Responses**: `200` [`CustomerOrgNrSearchResponse`](#schema-customerorgnrsearchresponse)[]

#### `GET /api/Customer/Common`

Return a list of top 5 common customers

**Responses**: `200` [`CustomerSearchResponse`](#schema-customersearchresponse)[]

#### `GET /api/Customer/Search`

Return a list of customer information based on given search filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SearchOrgNr` | query | `string` |  | Search by organization number |
| `SearchName` | query | `string` |  | Search by name |
| `SearchCity` | query | `string` |  | Search by city |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_SearchCustomerInformationResponse`](#schema-wint-utils-webapi-listresponseof-searchcustomerinformationresponse)

#### `GET /api/Customer/Rating`

Return the rating related to an organization number

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `CustomerId` | query | `integer(int32)` |  | Customer Id to check Rating |
| `OrgNr` | query | `string` |  | Organization Number to check Rating E.g. 123456-7890 |

**Responses**: `200` [`CustomerRating`](#schema-customerrating)

#### `POST /api/Customer/Activate/{id}`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `POST /api/Customer/Deactivate/{id}`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `POST /api/Customer/CustomerWithSameDetails`

Return details of an existing customer with the same information in customer

**Body**: [`ExistingCustomerCheckRequest`](#schema-existingcustomercheckrequest)

**Responses**: `200` [`ExistingCustomerCheckResponse`](#schema-existingcustomercheckresponse)

#### `GET /api/Customer/{id}/PenaltyInterestType`

Returns the default penalty interest type to use for a customer

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `customerId` | query | `integer(int32)` |  |  |
| `id` | path | `string` | yes |  |

**Responses**: `200` [`InvoicePenaltyInterestType`](#schema-invoicepenaltyinteresttype)

#### `GET /api/Customer/{id}/PenaltyInterestRate`

Returns the default penalty interest rate of the given type

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `customerId` | query | `integer(int32)` |  |  |
| `type` | query | [`InvoicePenaltyInterestType`](#schema-invoicepenaltyinteresttype) |  |  |
| `id` | path | `string` | yes |  |

**Responses**: `200` `number(double)`

#### `DELETE /api/Customer/Delete/{id}`

Delete a customer based on given id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `POST /api/Customer/ImportCustomers`

Import customers from given request

**Body**: [`CustomerImport`](#schema-customerimport)

**Responses**: `200` OK

<a id="tag-declaration"></a>
### Declaration

#### `POST /api/Declaration/SaveDeclaration`

Saves declaration data for a specific person and year.

**Body**: [`Declarations.Declaration`](#schema-declarations-declaration)

**Responses**: `200` OK; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `500` Internal Server Error

<a id="tag-dimension"></a>
### Dimension

#### `GET /api/Dimension`

Returns a list of dimensions based on given dimension filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `TypeId` | query | `string(uuid)` |  | Filters on a specific dimension type id |
| `CompatibilityType` | query | [`DimensionTypes`](#schema-dimensiontypes) |  | Dimension type, where 0 is CostCenter and 1 is Project |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Dimension`](#schema-wint-utils-webapi-listresponseof-dimension)

#### `POST /api/Dimension`

Creates a dimension

**Body**: [`DimensionPost`](#schema-dimensionpost)

**Responses**: `200` `string(uuid)`

#### `GET /api/Dimension/Invoices`

Returns dimensions available for invoices

**Responses**: `200` [`Dimension`](#schema-dimension)[]

#### `GET /api/Dimension/IncomingInvoices`

Returns dimensions available for incoming invoices

**Responses**: `200` [`Dimension`](#schema-dimension)[]

#### `GET /api/Dimension/Receipts`

Returns dimensions available for receipts

**Responses**: `200` [`Dimension`](#schema-dimension)[]

#### `PUT /api/Dimension/{id}`

Modify a dimension

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Body**: [`DimensionPut`](#schema-dimensionput)

**Responses**: `200` `string(uuid)`

#### `DELETE /api/Dimension/{id}`

Deletes a dimension

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` OK

<a id="tag-dimensiontypes"></a>
### DimensionTypes

#### `GET /api/DimensionTypes`

Filter DimensionTypes

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Name` | query | `string` |  | Name to filter on |
| `Types` | query | [`DimensionCompatibilityType`](#schema-dimensioncompatibilitytype)[] |  | Compatibility types to be included |
| `TypeIds` | query | `string(uuid)`[] |  | List of DimensionType Ids to be included |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_DimensionType`](#schema-wint-utils-webapi-listresponseof-dimensiontype)

#### `GET /api/DimensionTypes/IncomingInvoices`

Returns dimension types available for incoming invoices

**Responses**: `200` [`DimensionType`](#schema-dimensiontype)[]

#### `GET /api/DimensionTypes/Invoices`

Returns dimension types available for invoices

**Responses**: `200` [`DimensionType`](#schema-dimensiontype)[]

#### `GET /api/DimensionTypes/Receipts`

Returns dimension types available for receipts

**Responses**: `200` [`DimensionType`](#schema-dimensiontype)[]

<a id="tag-dimensionsreport"></a>
### DimensionsReport

#### `GET /api/DimensionsReport`

Get dimension report

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `StartMonth` | query | `string(date-time)` |  | Start month |
| `EndMonth` | query | `string(date-time)` |  | End Month |
| `TypeId` | query | `string(uuid)` |  | Dimension Type Id |
| `OnlyDimensionsWithTransactions` | query | `boolean` |  | True if only dimensions which has transaction in the given time period should be returned |
| `OnlyActiveDimensions` | query | `boolean` |  | True if only active dimensions should be returned, False if all should be returned. |

**Responses**: `200` [`Accounting.DimensionReport`](#schema-accounting-dimensionreport)

<a id="tag-document"></a>
### Document

#### `POST /api/Document/SIEFiles`

**Body**: [`SIEFilePost`](#schema-siefilepost)

**Responses**: `200` OK

<a id="tag-employees"></a>
### Employees

#### `GET /api/Employees`

Returns a list of emplpoyees based on filter provided

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Employee`](#schema-wint-utils-webapi-listresponseof-employee)

#### `POST /api/Employees`

Creates a employee given by Wint.Superkoll.API.Model.EmployeePost

**Body**: [`EmployeePost`](#schema-employeepost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Employees/{id}`

Return the employee given by the id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the employee |

**Responses**: `200` [`ExtendedEmployee`](#schema-extendedemployee)

#### `PUT /api/Employees/{id}`

Update employee

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the employee |

**Body**: [`EmployeePut`](#schema-employeeput)

**Responses**: `200` `integer(int32)`

#### `DELETE /api/Employees/{id}`

Delete the employee given in Id Optional to provide a date for employment end

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |
| `EmploymentEndDate` | query | `string(date-time)` |  | The date of ending employment |

**Responses**: `200` OK

<a id="tag-financialreports"></a>
### FinancialReports

#### `POST /api/FinancialReports/ResultReport`

Get result report

**Body**: [`FinancialReport.FinancialReportFilter`](#schema-financialreport-financialreportfilter)

**Responses**: `200` [`FinancialReport.FinancialReport`](#schema-financialreport-financialreport)

#### `POST /api/FinancialReports/MonthlyResultReport`

Get monthly result report

**Body**: [`FinancialReport.FinancialReportMonthlyFilter`](#schema-financialreport-financialreportmonthlyfilter)

**Responses**: `200` [`FinancialReport.FinancialReport`](#schema-financialreport-financialreport)

#### `POST /api/FinancialReports/BalanceReport`

Get balance report

**Body**: [`FinancialReport.FinancialReportFilter`](#schema-financialreport-financialreportfilter)

**Responses**: `200` [`FinancialReport.FinancialReport`](#schema-financialreport-financialreport)

#### `POST /api/FinancialReports/Audit/BalanceReport`

Get the audit balance reconciliation report

**Body**: [`FinancialReport.AuditReportFilter`](#schema-financialreport-auditreportfilter)

**Responses**: `200` [`FinancialReport.FinancialReport`](#schema-financialreport-financialreport)

#### `GET /api/FinancialReports/Audit/BalanceReportFilterData`

Get valid filter values for the Audit balance report

**Responses**: `200` [`FinancialReport.AuditReportFilterData`](#schema-financialreport-auditreportfilterdata)

#### `POST /api/FinancialReports/MonthlyBalanceReport`

Get monthly balance report

**Body**: [`FinancialReport.FinancialReportMonthlyFilter`](#schema-financialreport-financialreportmonthlyfilter)

**Responses**: `200` [`FinancialReport.FinancialReport`](#schema-financialreport-financialreport)

#### `POST /api/FinancialReports/DimensionReport`

Get dimension report

**Body**: [`FinancialReport.FinancialReportDimensionFilter`](#schema-financialreport-financialreportdimensionfilter)

**Responses**: `200` [`FinancialReport.FinancialReport`](#schema-financialreport-financialreport)

#### `POST /api/FinancialReports/MultiDimensionReport`

Get multi dimensional dimensions report

**Body**: [`FinancialReport.FinancialReportMultiDimensionFilter`](#schema-financialreport-financialreportmultidimensionfilter)

**Responses**: `200` [`FinancialReport.FinancialReport`](#schema-financialreport-financialreport)

#### `GET /api/FinancialReports/{financialYearId}/LastReconciliationId`

Retrieves the last monthly reconciliation id for the given financial year id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `financialYearId` | path | `integer(int32)` | yes | The financial year id |

**Responses**: `200` [`FinancialReport.AuditReportFilterItem`](#schema-financialreport-auditreportfilteritem)

<a id="tag-invoice"></a>
### Invoice

#### `GET /api/Invoice`

Returns a list of invoices based on given invoice filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SerialNumber` | query | `integer(int64)` |  | Obsolete property. use MinSerialNumber instead. If this is used, MinSerialNumber and MaxSerialNumber will not be applied |
| `Ocr` | query | `integer(int64)` |  | OCR number on invoice |
| `Credit` | query | `boolean` |  | Regular invoice or credit invoice |
| `Rot` | query | `boolean` |  | Invoice contains rot |
| `Rut` | query | `boolean` |  | Invoice contains rut |
| `LastUpdated` | query | `string(date-time)` |  | Only include invoices where LastUpdate is greater or equal |
| `Statuses` | query | [`InvoiceStatus`](#schema-invoicestatus)[] |  | Only include invoices which is in one of the provided state. Empty list will include all. 0 - Invoice is not sent 1 - Invoice is unpaid 2 - Invoice is overdue and reminder has been sent 3 - Invoice is overdue and reminder has not been sent 4 - Invoice is paid 5 - Invoice is cancelled 6 - Invoice is in debt collection |
| `CustomerId` | query | `integer(int32)` |  | Obsolete property. Use CustomerIds instead. |
| `ArticleIds` | query | `integer(int32)`[] |  | Only include invoices which contain provided articles. |
| `OwnerIds` | query | `integer(int32)`[] |  | Only include invoices with given owners. |
| `CustomerIds` | query | `integer(int32)`[] |  | Only include invoices of customer with given Wint.Superkoll.API.Model.Customer |
| `MinSerialNumber` | query | `integer(int32)` |  | Include invoices with serial number greater than or equal this. |
| `MaxSerialNumber` | query | `integer(int32)` |  | Include invoices with serial number less than or equal this. |
| `InvoiceDateFrom` | query | `string(date-time)` |  | Include invoices with posting date after this date. |
| `InvoiceDateTo` | query | `string(date-time)` |  | Include invoices with posting date before this date. |
| `DueDateFrom` | query | `string(date-time)` |  | Include invoices which are going to due after this date. |
| `DueDateTo` | query | `string(date-time)` |  | Include invoices which are going to due before this date. |
| `MinTotalAmount` | query | `number(double)` |  | Include incoming invoices having an invoiced amount greater than or equal this. |
| `MaxTotalAmount` | query | `number(double)` |  | Include incoming invoices having an invoiced amount less than or equal this. |
| `ShowCreditSameMonth` | query | `boolean` |  | View credit invoices during the month of the original invoice. Default value is false. |
| `PaymentStatuses` | query | [`InvoicePaymentState`](#schema-invoicepaymentstate)[] |  | Include invoices with these payment statuses. |
| `MinUnpaidAmount` | query | `number(double)` |  | Include invoice with unpaid amount greater than or equal this. |
| `MaxUnpaidAmount` | query | `number(double)` |  | Include invoice with unpaid amount less than or equal this. |
| `SnapshotDate` | query | `string(date-time)` |  | Snapshot of the current states of all transactions recorded up until this date |
| `CreditStatuses` | query | [`InvoiceCreditStatus`](#schema-invoicecreditstatus)[] |  | Include invoice with these credit statuses |
| `HouseWorkInvoice` | query | `boolean` |  | Include invoices with Rut/Rot |
| `RecurringInvoiceId` | query | `integer(int32)` |  | Include invoices created from the referenced recurring invoice |
| `Dimensions` | query | `string(uuid)`[] |  | Only include invoices having these dimensions. Will be OR between dimensions within same dimension type and AND between different dimension types |
| `ShowAgentInvoices` | query | [`DownPaymentVisibility`](#schema-downpaymentvisibility) |  | Include comission- and/or downpayment invoices. |
| `ExcludeTimeReportingInvoices` | query | `boolean` |  | Exclude time reporting invoices |
| `SerialNumberSearchText` | query | `string` |  | Serial Number Search Text |
| `SelfInvoiceId` | query | `string(uuid)` |  | Related self invoice id |
| `Sources` | query | [`InvoiceSource`](#schema-invoicesource)[] |  | Include invoices with these sources |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Invoice`](#schema-wint-utils-webapi-listresponseof-invoice)

#### `POST /api/Invoice`

Creates an invoice based on given invoice data

Note: the status 400 error code UncategorizedEuCustomerInvoiceItems deserves special mention. It is issued for invoices to EU customers when no invoice item EU VAT product type has been specified. These are necessary for generating the recapitulative statement and can be set for invoice items directly, but preferrably at Wint.Superkoll.API.Model.Article level. Valid values are: - 1 (Unknown) - 2 (Exempt) - 24 (Goods) - 28 (Services) - 27 (ThirdPartyTrade)

**Body**: [`InvoicePost`](#schema-invoicepost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Invoice/List`

Returns a list of invoices based on given invoice filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SerialNumber` | query | `integer(int64)` |  | Obsolete property. use MinSerialNumber instead. If this is used, MinSerialNumber and MaxSerialNumber will not be applied |
| `Ocr` | query | `integer(int64)` |  | OCR number on invoice |
| `Credit` | query | `boolean` |  | Regular invoice or credit invoice |
| `Rot` | query | `boolean` |  | Invoice contains rot |
| `Rut` | query | `boolean` |  | Invoice contains rut |
| `LastUpdated` | query | `string(date-time)` |  | Only include invoices where LastUpdate is greater or equal |
| `Statuses` | query | [`InvoiceStatus`](#schema-invoicestatus)[] |  | Only include invoices which is in one of the provided state. Empty list will include all. 0 - Invoice is not sent 1 - Invoice is unpaid 2 - Invoice is overdue and reminder has been sent 3 - Invoice is overdue and reminder has not been sent 4 - Invoice is paid 5 - Invoice is cancelled 6 - Invoice is in debt collection |
| `CustomerId` | query | `integer(int32)` |  | Obsolete property. Use CustomerIds instead. |
| `ArticleIds` | query | `integer(int32)`[] |  | Only include invoices which contain provided articles. |
| `OwnerIds` | query | `integer(int32)`[] |  | Only include invoices with given owners. |
| `CustomerIds` | query | `integer(int32)`[] |  | Only include invoices of customer with given Wint.Superkoll.API.Model.Customer |
| `MinSerialNumber` | query | `integer(int32)` |  | Include invoices with serial number greater than or equal this. |
| `MaxSerialNumber` | query | `integer(int32)` |  | Include invoices with serial number less than or equal this. |
| `InvoiceDateFrom` | query | `string(date-time)` |  | Include invoices with posting date after this date. |
| `InvoiceDateTo` | query | `string(date-time)` |  | Include invoices with posting date before this date. |
| `DueDateFrom` | query | `string(date-time)` |  | Include invoices which are going to due after this date. |
| `DueDateTo` | query | `string(date-time)` |  | Include invoices which are going to due before this date. |
| `MinTotalAmount` | query | `number(double)` |  | Include incoming invoices having an invoiced amount greater than or equal this. |
| `MaxTotalAmount` | query | `number(double)` |  | Include incoming invoices having an invoiced amount less than or equal this. |
| `ShowCreditSameMonth` | query | `boolean` |  | View credit invoices during the month of the original invoice. Default value is false. |
| `PaymentStatuses` | query | [`InvoicePaymentState`](#schema-invoicepaymentstate)[] |  | Include invoices with these payment statuses. |
| `MinUnpaidAmount` | query | `number(double)` |  | Include invoice with unpaid amount greater than or equal this. |
| `MaxUnpaidAmount` | query | `number(double)` |  | Include invoice with unpaid amount less than or equal this. |
| `SnapshotDate` | query | `string(date-time)` |  | Snapshot of the current states of all transactions recorded up until this date |
| `CreditStatuses` | query | [`InvoiceCreditStatus`](#schema-invoicecreditstatus)[] |  | Include invoice with these credit statuses |
| `HouseWorkInvoice` | query | `boolean` |  | Include invoices with Rut/Rot |
| `RecurringInvoiceId` | query | `integer(int32)` |  | Include invoices created from the referenced recurring invoice |
| `Dimensions` | query | `string(uuid)`[] |  | Only include invoices having these dimensions. Will be OR between dimensions within same dimension type and AND between different dimension types |
| `ShowAgentInvoices` | query | [`DownPaymentVisibility`](#schema-downpaymentvisibility) |  | Include comission- and/or downpayment invoices. |
| `ExcludeTimeReportingInvoices` | query | `boolean` |  | Exclude time reporting invoices |
| `SerialNumberSearchText` | query | `string` |  | Serial Number Search Text |
| `SelfInvoiceId` | query | `string(uuid)` |  | Related self invoice id |
| `Sources` | query | [`InvoiceSource`](#schema-invoicesource)[] |  | Include invoices with these sources |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_InvoiceListItem`](#schema-wint-utils-webapi-listresponseof-invoicelistitem)

#### `GET /api/Invoice/Todos`

Return a list of Invoice Todos based on given filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SerialNumber` | query | `integer(int64)` |  | Obsolete property. use MinSerialNumber instead. If this is used, MinSerialNumber and MaxSerialNumber will not be applied |
| `Ocr` | query | `integer(int64)` |  | OCR number on invoice |
| `Credit` | query | `boolean` |  | Regular invoice or credit invoice |
| `Rot` | query | `boolean` |  | Invoice contains rot |
| `Rut` | query | `boolean` |  | Invoice contains rut |
| `LastUpdated` | query | `string(date-time)` |  | Only include invoices where LastUpdate is greater or equal |
| `Statuses` | query | [`InvoiceStatus`](#schema-invoicestatus)[] |  | Only include invoices which is in one of the provided state. Empty list will include all. 0 - Invoice is not sent 1 - Invoice is unpaid 2 - Invoice is overdue and reminder has been sent 3 - Invoice is overdue and reminder has not been sent 4 - Invoice is paid 5 - Invoice is cancelled 6 - Invoice is in debt collection |
| `CustomerId` | query | `integer(int32)` |  | Obsolete property. Use CustomerIds instead. |
| `ArticleIds` | query | `integer(int32)`[] |  | Only include invoices which contain provided articles. |
| `OwnerIds` | query | `integer(int32)`[] |  | Only include invoices with given owners. |
| `CustomerIds` | query | `integer(int32)`[] |  | Only include invoices of customer with given Wint.Superkoll.API.Model.Customer |
| `MinSerialNumber` | query | `integer(int32)` |  | Include invoices with serial number greater than or equal this. |
| `MaxSerialNumber` | query | `integer(int32)` |  | Include invoices with serial number less than or equal this. |
| `InvoiceDateFrom` | query | `string(date-time)` |  | Include invoices with posting date after this date. |
| `InvoiceDateTo` | query | `string(date-time)` |  | Include invoices with posting date before this date. |
| `DueDateFrom` | query | `string(date-time)` |  | Include invoices which are going to due after this date. |
| `DueDateTo` | query | `string(date-time)` |  | Include invoices which are going to due before this date. |
| `MinTotalAmount` | query | `number(double)` |  | Include incoming invoices having an invoiced amount greater than or equal this. |
| `MaxTotalAmount` | query | `number(double)` |  | Include incoming invoices having an invoiced amount less than or equal this. |
| `ShowCreditSameMonth` | query | `boolean` |  | View credit invoices during the month of the original invoice. Default value is false. |
| `PaymentStatuses` | query | [`InvoicePaymentState`](#schema-invoicepaymentstate)[] |  | Include invoices with these payment statuses. |
| `MinUnpaidAmount` | query | `number(double)` |  | Include invoice with unpaid amount greater than or equal this. |
| `MaxUnpaidAmount` | query | `number(double)` |  | Include invoice with unpaid amount less than or equal this. |
| `SnapshotDate` | query | `string(date-time)` |  | Snapshot of the current states of all transactions recorded up until this date |
| `CreditStatuses` | query | [`InvoiceCreditStatus`](#schema-invoicecreditstatus)[] |  | Include invoice with these credit statuses |
| `HouseWorkInvoice` | query | `boolean` |  | Include invoices with Rut/Rot |
| `RecurringInvoiceId` | query | `integer(int32)` |  | Include invoices created from the referenced recurring invoice |
| `Dimensions` | query | `string(uuid)`[] |  | Only include invoices having these dimensions. Will be OR between dimensions within same dimension type and AND between different dimension types |
| `ShowAgentInvoices` | query | [`DownPaymentVisibility`](#schema-downpaymentvisibility) |  | Include comission- and/or downpayment invoices. |
| `ExcludeTimeReportingInvoices` | query | `boolean` |  | Exclude time reporting invoices |
| `SerialNumberSearchText` | query | `string` |  | Serial Number Search Text |
| `SelfInvoiceId` | query | `string(uuid)` |  | Related self invoice id |
| `Sources` | query | [`InvoiceSource`](#schema-invoicesource)[] |  | Include invoices with these sources |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Invoice`](#schema-wint-utils-webapi-listresponseof-invoice)

#### `GET /api/Invoice/{id}`

Returns an invoice based on given invoice id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Invoice`](#schema-invoice)

#### `POST /api/Invoice/{id}`

Sends the invoice corresponding to the given id by the help of the given options.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the invoice. |

**Body**: [`InvoiceSendProperties`](#schema-invoicesendproperties)

**Responses**: `200` OK

#### `PUT /api/Invoice/{id}`

Update the invoice based on given id and invoicePut

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`InvoicePut`](#schema-invoiceput)

**Responses**: `200` `integer(int32)`

#### `DELETE /api/Invoice/{id}`

Delete an invoice (status will be set to canceled). An invoice can only be deleted if it has not been sent.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice to be deleted |

**Responses**: `200` OK

#### `GET /api/Invoice/DimensionSuggestions`

**Responses**: `200` `string(uuid)`[]

#### `PUT /api/Invoice/{id}/periodisations`

Replaces the periodisation state of one or more invoice items on the invoice identified by id. Rows for items not in body are left untouched (partial PUT). Periodisation cannot be edited on cancelled invoices.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the invoice. |

**Body**: [`InvoicePeriodisationsPut`](#schema-invoiceperiodisationsput)

**Responses**: `200` OK

#### `POST /api/Invoice/Send/{id}`

Sends the invoice corresponding to the given id by the help of the given options.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the invoice. |

**Body**: [`InvoiceSendProperties`](#schema-invoicesendproperties)

**Responses**: `200` OK

#### `POST /api/Invoice/{id}/Mail`

Email a specific version of a invoice corresponding to the given id by the help of the given options.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the invoice. |

**Body**: [`InvoiceSendProperties`](#schema-invoicesendproperties)

**Responses**: `200` OK

#### `POST /api/Invoice/{id}/SendEInvoice`

Sends the latest version of a invoice as a electronic invoice or print corresponding to the given id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the invoice. |

**Responses**: `200` OK

#### `POST /api/Invoice/{id}/WriteOffReminderFee`

Write off the unpaid reminder fee and penalty interest for an invoice. The invoice must be in ReminderFeeNotFullyPaid status.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the invoice. |

**Responses**: `200` OK

#### `GET /api/Invoice/{invoiceId}/transactions`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Accounting.SimplifiedVoucher`](#schema-accounting-simplifiedvoucher)[]

#### `GET /api/Invoice/{invoiceId}/attachments`

Returns a list ids of all attachments linked to an invioce

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | path | `integer(int32)` | yes | The id of the invoice |

**Responses**: `200` `string(uuid)`[]

#### `POST /api/Invoice/{invoiceId}/attachments`

Add an attachment to an invoice

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | path | `integer(int32)` | yes | The id of the invoice to which the attachment should be added |

**Body**: [`InvoiceAttachmentPost`](#schema-invoiceattachmentpost)

**Responses**: `200` OK

#### `POST /api/Invoice/{invoiceId}/AttachmentList`

Add a list of attachments to an invoice

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | path | `integer(int32)` | yes | The id of the invoice to which the attachment should be added |

**Body**: [`InvoiceAttachmentPost`](#schema-invoiceattachmentpost)[]

**Responses**: `200` OK

#### `GET /api/Invoice/{invoiceId}/attachments/{attachmentId}`

Returns an invoice attachment

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | path | `integer(int32)` | yes | Id of the invoice which has the attachment |
| `attachmentId` | path | `string(uuid)` | yes | Id of the attachment to be returned |

**Responses**: `200` [`InvoiceAttachment`](#schema-invoiceattachment)

#### `DELETE /api/Invoice/{invoiceId}/attachments/{attachmentId}`

Delete an invoice attachment.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | path | `integer(int32)` | yes | Id of the invoice which has the attachment |
| `attachmentId` | path | `string(uuid)` | yes | Id of the attachment to be deleted |

**Responses**: `200` OK

#### `GET /api/Invoice/StateLogs/{id}`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`EntityStateLog`](#schema-entitystatelog)[]

#### `GET /api/Invoice/FindSimilar/{id}`

Return a list of similar invoices based on given invoice id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |
| `limit` | query | `integer(int32)` |  |  |

**Responses**: `200` [`InvoiceSimilarItem`](#schema-invoicesimilaritem)[]

#### `GET /api/Invoice/{id}/pdf/{version}`

Returns the invoice as a pdf document

For an invoice to be available as a pdf it must have been sent, ie. it needs to have moved past the state 0 - NotSent.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice |
| `version` | path | `integer(int32)` | yes | Version number of the pdf If omitted, the version, if any, saved last will be returned. 0 - invoice, 1 - reminder 1, 2 - reminder 2 |

**Responses**: `200` [`InvoicePdf`](#schema-invoicepdf)

#### `POST /api/Invoice/EditDueDate/{id}`

Edit payments in the invoice

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice |

**Body**: [`InvoiceDue`](#schema-invoicedue)

**Responses**: `200` OK

#### `POST /api/Invoice/ReportAsPaid/{id}`

Edit payments in the invoice

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice |

**Body**: [`ReportPaymentRequest`](#schema-reportpaymentrequest)

**Responses**: `200` OK

#### `GET /api/Invoice/{id}/Preview/{version}`

Returns the invoice pdf in html based on given id and version

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice |
| `version` | path | `integer(int32)` | yes | Version number of the pdf |

**Responses**: `200` `string`

#### `POST /api/Invoice/{id}/ReminderPreview`

Return a preview of invoice reminder pdf in html.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`InvoicePaymentReminder`](#schema-invoicepaymentreminder)

**Responses**: `200` `string`

#### `POST /api/Invoice/SendPaymentReminder/{id}`

Send a payment reminder

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice |

**Body**: [`InvoicePaymentReminder`](#schema-invoicepaymentreminder)

**Responses**: `200` OK

#### `POST /api/Invoice/Preview`

Returns the preview of the invoice in html based on given post

**Body**: [`InvoicePreviewRequest`](#schema-invoicepreviewrequest)

**Responses**: `200` OK

#### `POST /api/Invoice/Warnings`

Returns the warnings of an invoice based on given post

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | query | `integer(int32)` |  | The saved draft being edited, if any, so the costs already reserved on it are checked too. |

**Body**: [`InvoicePost`](#schema-invoicepost)

**Responses**: `200` [`Warning`](#schema-warning)[]

#### `GET /api/Invoice/CommonSellers`

Return the names of top 5 sellers

**Responses**: `200` `string`[]

#### `PUT /api/Invoice/{invoiceId}/UpdateDimension`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `invoiceId` | path | `integer(int32)` | yes |  |

**Body**: [`InvoiceDimensionPut`](#schema-invoicedimensionput)

**Responses**: `200` OK

#### `GET /api/Invoice/{id}/CreateCreditInvoice`

Return credit invoice for the invoice given by invoice id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Invoice`](#schema-invoice)

#### `POST /api/Invoice/{id}/CreditAndReissue/Changes`

Returns which field groups differ between the sent invoice given by id and the edited invoice payload, for the credit-and-reissue confirmation step.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the original, sent invoice. |

**Body**: [`CreditAndReissueChangesPost`](#schema-creditandreissuechangespost)

**Responses**: `200` [`InvoiceChangedFieldGroup`](#schema-invoicechangedfieldgroup)[]

#### `POST /api/Invoice/{id}/CreditAndReissue`

Credits the sent invoice given by id in full and creates a replacement invoice from the edited payload, then sends both according to the given send options. The two creations are not transactional: if the replacement cannot be created the credit note is cancelled again, and if a send fails the unsent invoices are cancelled. The returned errors describe the resulting state; a credit note that was already sent is never undone.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the original, sent invoice. |

**Body**: [`CreditAndReissuePost`](#schema-creditandreissuepost)

**Responses**: `200` [`CreditAndReissueResult`](#schema-creditandreissueresult)

#### `GET /api/Invoice/{id}/downloadPDF/{version}`

Returns the invoice as a pdf document in a format easier to be downloaded

For an invoice to be available as a pdf it must have been sent, ie. it needs to have moved past the state 0 - NotSent.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice |
| `version` | path | `integer(int32)` | yes | Version number of the pdf If omitted, the version, if any, saved last will be returned. 0 - invoice, 1 - reminder 1, 2 - reminder 2 |

**Responses**: `200` OK

#### `GET /api/Invoice/DefaultMailOptions/{invoiceId}`

Get default information to send mail

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Version` | query | `integer(int32)` |  | Get e-mail options for a specific version |
| `CustomerId` | query | `integer(int32)` |  | Invoice customer Id |
| `invoiceId` | path | `integer(int32)` | yes | reference to the id of invoice |

**Responses**: `200` [`InvoiceDefaultMailOptions`](#schema-invoicedefaultmailoptions)

#### `POST /api/Invoice/{id}/CreateRecurringInvoice`

Returns the recurring invoice for the given customer invoice

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the customer invoice |

**Responses**: `200` [`RecurringInvoice`](#schema-recurringinvoice)

#### `GET /api/Invoice/GetInvoicePersons`

Returns employees with invoice permissions

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SearchStr` | query | `string` |  | Search string for invoice person name |
| `IncludeSelf` | query | `boolean` |  | If needs to include or exclude the current user |
| `ExcludeIds` | query | `integer(int32)`[] |  | If needs to exclude some users |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-listresponseof-wint-utils-webapi-searchresult)

#### `GET /api/Invoice/GetInvoicePersonSuggestions`

Returns frequently used invoice owners

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Count` | query | `integer(int32)` |  | number of max persons to be fetched |
| `IncludeSelf` | query | `boolean` |  | If needs to include or exclude the current user |
| `ExcludeIds` | query | `integer(int32)`[] |  | If needs to exclude some users |

**Responses**: `200` [`InvoicePersonsSuggestionCollection`](#schema-invoicepersonssuggestioncollection)

#### `PUT /api/Invoice/{id}/ReassignOwner`

Changes the owner of the invoice given by id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`InvoiceOwnerReassignRequest`](#schema-invoiceownerreassignrequest)

**Responses**: `200` OK

#### `GET /api/Invoice/RutRotWorkTypes`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Type` | query | [`InvoiceHouseWorkType`](#schema-invoicehouseworktype) |  | Include house work types with this type (Rut/Rot) |
| `Name` | query | `string` |  | Include house work types with this name |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_RutRotWorkType`](#schema-wint-utils-webapi-listresponseof-rutrotworktype)

#### `POST /api/Invoice/DisableAutomaticReminders/{id}`

Disable automatic reminders if enabled

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the invoice |

**Responses**: `200` OK

#### `GET /api/Invoice/{id}/Copy`

Returns a copy of invoice given by id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Invoice`](#schema-invoice)

#### `GET /api/Invoice/{id}/Versions`

Returns different version information of an invoice given by id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`InvoiceVersionInfo`](#schema-invoiceversioninfo)[]

#### `POST /api/Invoice/Activate`

**Body**: [`InvoiceActivationRequest`](#schema-invoiceactivationrequest)

**Responses**: `200` OK

#### `GET /api/Invoice/GetNextCompanyInvoiceSerialNumber`

**Responses**: `200` `integer(int32)`

<a id="tag-invoicepaymentoption"></a>
### InvoicePaymentOption

#### `GET /api/InvoicePaymentOption`

Get available payment options

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_InvoicePaymentOption`](#schema-wint-utils-webapi-listresponseof-invoicepaymentoption)

<a id="tag-missingdocument"></a>
### MissingDocument

#### `PUT /api/MissingDocument/{id}`

Updates a missing document

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`MissingDocumentPut`](#schema-missingdocumentput)

**Responses**: `200` `integer(int32)`

#### `GET /api/MissingDocument/{missingDocumentId}/Attachments/{attachmentId}`

Returns the attachment corresponding to the given attachmentId that is associated with the given missingDocumentId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `missingDocumentId` | path | `integer(int32)` | yes | The id of the missing document |
| `attachmentId` | path | `integer(int32)` | yes | The id of the attachment |

**Responses**: `200` [`MissingDocumentAttachment`](#schema-missingdocumentattachment)

#### `GET /api/MissingDocument/Pdf/{id}`

Download the missing document attachments as PDF

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

<a id="tag-monthlyreports"></a>
### MonthlyReports

#### `GET /api/MonthlyReports`

List the selected company's monthly reports in any state.

The reviewer's list: drafts, reports still generating and failed passes included, unlike the customer's list. Newest period first. Takes the shared list filter: 0-based `page`, `numPerPage` (100 when omitted, capped by the report service at 1000), `isAutoPaginating` for everything in one page, and `status`, which may be repeated. Ordering properties are ignored. Read a full report with `GET api/MonthlyReports/{id}`.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Status` | query | [`MonthlyReportStatus`](#schema-monthlyreportstatus)[] |  | Optional: only reports in these states. Omit for every state. |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_MonthlyReportSummary`](#schema-wint-utils-webapi-listresponseof-monthlyreportsummary); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `POST /api/MonthlyReports`

Generate a monthly report for the selected company and a calendar month.

Returns as soon as the report exists, in `Generating`. The generation pass itself takes 15-90 seconds and runs in the report service's background; poll `GET api/MonthlyReports/{id}` until the status changes. Posting a month whose earlier pass failed retries it on the same report. Posting a month that already has a finished report is refused with a validation error.

**Body**: [`GenerateMonthlyReportRequest`](#schema-generatemonthlyreportrequest)

**Responses**: `200` [`MonthlyReportSummary`](#schema-monthlyreportsummary); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `409` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `GET /api/MonthlyReports/{id}`

Get a monthly report in any state, body and history included.

Shows drafts and reports still generating, so this is the endpoint to poll after generating: the status moves from `Generating` to `Draft`, or to `Failed` if the pass threw, in which case posting the same period again retries it.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |

**Responses**: `200` [`MonthlyReport`](#schema-monthlyreport); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `POST /api/MonthlyReports/{id}/regenerate`

Run another generation pass over a report, optionally guided by feedback.

Synchronous: the response arrives when the new iteration exists, typically after 15-90 seconds.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |

**Body**: [`RegenerateMonthlyReportRequest`](#schema-regeneratemonthlyreportrequest)

**Responses**: `200` [`MonthlyReport`](#schema-monthlyreport); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `PUT /api/MonthlyReports/{id}/markdown`

Replace the report body with a hand-edited version.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |

**Body**: [`EditMonthlyReportMarkdownRequest`](#schema-editmonthlyreportmarkdownrequest)

**Responses**: `200` [`MonthlyReport`](#schema-monthlyreport); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `POST /api/MonthlyReports/{id}/approve`

Approve the current iteration for the customer.

This is the step that reaches the customer: the report becomes visible to them and a support case carrying the link is opened. It is recorded against the signed-in user.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |

**Responses**: `200` [`MonthlyReport`](#schema-monthlyreport); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `POST /api/MonthlyReports/{id}/unpublish`

Revoke an approval, returning the report to draft so the customer can no longer read it.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |

**Responses**: `200` [`MonthlyReport`](#schema-monthlyreport); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `GET /api/MonthlyReports/CompanyInstruction`

Get the selected company's monthly-report instruction.

The advisor's standing guidance for this company's reports: focus, interpretation and tone. It applies to every later generation and regeneration. `text` is null when the company has none.

**Responses**: `200` [`MonthlyReportCompanyInstruction`](#schema-monthlyreportcompanyinstruction); `403` No permission

#### `PUT /api/MonthlyReports/CompanyInstruction`

Save the selected company's monthly-report instruction.

Replaces the instruction; empty text removes it. Reports already generated are unchanged until they are regenerated.

**Body**: [`MonthlyReportCompanyInstruction`](#schema-monthlyreportcompanyinstruction)

**Responses**: `200` [`MonthlyReportCompanyInstruction`](#schema-monthlyreportcompanyinstruction); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

<a id="tag-profileroutine"></a>
### ProfileRoutine

#### `PUT /api/ProfileRoutine/{id}`

Updates a routine corresponding to the given id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`ProfileRoutinePut`](#schema-profileroutineput)

**Responses**: `200` `integer(int32)`

<a id="tag-receipt"></a>
### Receipt

#### `GET /api/Receipt/{id}`

Returns a receipt based on given receipt id

**Client Capabilities:** To receive receipts with null PaymentMethodId, include the following header: - `X-Wint-Capabilities: ReceiptPaymentMethodNullability` Without this header, receipts with null PaymentMethodId will be filtered out (return 404 for Get by id, excluded from list responses). The header supports comma-separated capabilities: `X-Wint-Capabilities: ReceiptPaymentMethodNullability,FeatureX,FeatureY`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Receipt id |

**Responses**: `200` [`Receipt`](#schema-receipt)

#### `PUT /api/Receipt/{id}`

Update a receipt based on id and receipt data

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`ReceiptPut`](#schema-receiptput)

**Responses**: `200` `integer(int32)`

#### `GET /api/Receipt`

Returns a list of receipts based on given receipt filter

**Client Capabilities:** To receive receipts with null PaymentMethodId, include the following header: - `X-Wint-Capabilities: ReceiptPaymentMethodNullability` Without this header, receipts with null PaymentMethodId will be filtered out (return 404 for Get by id, excluded from list responses). The header supports comma-separated capabilities: `X-Wint-Capabilities: ReceiptPaymentMethodNullability,FeatureX,FeatureY`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `State` | query | [`ReceiptStateApiModel`](#schema-receiptstateapimodel) |  | Include only receipts with this state |
| `States` | query | [`ReceiptStateApiModel`](#schema-receiptstateapimodel)[] |  | Include receipts only with these states |
| `ReceiptCategoryId` | query | `integer(int32)` |  | Include receipts only having this category Id |
| `ReceiptCategories` | query | `integer(int32)`[] |  | Include receipts only having this category Id |
| `CreatedFromDate` | query | `string(date-time)` |  | Include receipts created after this date |
| `CreatedToDate` | query | `string(date-time)` |  | Include receipts created before this date |
| `AmountFrom` | query | `number(double)` |  | Include receipts having an amount greater than this |
| `AmountTo` | query | `number(double)` |  | Include receipts having an amount less than this |
| `Currency` | query | `string` |  | Include receipts only having this currency |
| `UploadedByUserIds` | query | `integer(int32)`[] |  | Include receipts only uploaded by these person Ids |
| `PaymentState` | query | [`PaymentState`](#schema-paymentstate) |  | Include receipts only having given payment status. If no value was provided both paid and unpaid receipts will be returned. |
| `LastUpdated` | query | `string(date-time)` |  | Include only receipts that has been modified at this date and time or later |
| `ClientId` | query | `string(uuid)` |  | Include only receipts with this client id |
| `Dimensions` | query | `string(uuid)`[] |  | Only include receipts having these dimensions |
| `SerialNumberFrom` | query | `integer(int32)` |  | Include receipts having a receipt number greater than this |
| `SerialNumberTo` | query | `integer(int32)` |  | Include receipts having a receipt number less than this |
| `PaymentMethods` | query | `integer(int32)`[] |  | Include receipts having a these payment methods |
| `PaymentMethodTypes` | query | `integer(int32)`[] |  | Include receipts having a these payment method types |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Receipt`](#schema-wint-utils-webapi-listresponseof-receipt)

#### `POST /api/Receipt`

Create a new receipt based on receipt data

**Body**: [`ReceiptPost`](#schema-receiptpost)

**Responses**: `200` `integer(int32)`

#### `POST /api/Receipt/Cancel/{id}`

Cancels the receipt corresponding to the given id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the receipt. |

**Responses**: `200` OK

#### `POST /api/Receipt/Sign/{id}`

Signs the receipt with the given id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the receipt. |

**Responses**: `200` OK

#### `POST /api/Receipt/UpdateAndSign/{id}`

Update the receipt, and signs the receipt with the given id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the receipt. |

**Body**: [`ReceiptPut`](#schema-receiptput)

**Responses**: `200` `integer(int32)`

#### `POST /api/Receipt/SendBack/{id}`

Sends the receipt corresponding to the given id back to its owner.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the receipt. |

**Body**: [`ReceiptSendBackData`](#schema-receiptsendbackdata)

**Responses**: `200` OK

#### `GET /api/Receipt/{receiptId}/Attachments/{attachmentId}`

Returns the attachment corresponding to the given attachmentId associated with the given receiptId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `receiptId` | path | `integer(int32)` | yes | The id of the receipt. |
| `attachmentId` | path | `integer(int32)` | yes | The id of the attachment. |

**Responses**: `200` [`ReceiptAttachment`](#schema-receiptattachment)

#### `DELETE /api/Receipt/{receiptId}/Images/{imageId}`

Deletes the image corresponding to the given imageId of the receipt corresponding to the given receiptId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `receiptId` | path | `integer(int32)` | yes | The id of the receipt. |
| `imageId` | path | `integer(int32)` | yes | The id of the image. |

**Responses**: `200` OK

#### `GET /api/Receipt/AllReceiptPersons`

Returns a set of all receipt persons from ReceiptAddressBook.

**Responses**: `200` [`ReceiptPerson`](#schema-receiptperson)[]

#### `GET /api/Receipt/CommonReceiptPersons`

Returns a set of twenty receipt persons from last six months.

**Responses**: `200` [`ReceiptPerson`](#schema-receiptperson)[]

#### `POST /api/Receipt/AddReceiptPerson`

Add ReceiptPerson to the ReceiptAddressBook.

**Body**: [`ReceiptPerson`](#schema-receiptperson)

**Responses**: `200` `integer(int32)`

#### `DELETE /api/Receipt/RemoveReceiptPerson/{personId}`

Remove the receipt person from ReceiptAddressBook.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `personId` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `GET /api/Receipt/GetPdfAsync/{id}`

Download the receipt attachments as PDF

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Receipt id |

**Responses**: `200` OK

#### `GET /api/Receipt/SimilarAsync/{id}`

Return a list of similar receipts based on given receipt id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Receipt id |
| `limit` | query | `integer(int32)` |  | Maximum no of list items |

**Responses**: `200` [`ReceiptsSimilarItem`](#schema-receiptssimilaritem)[]

#### `GET /api/Receipt/Transactions/{id}`

Gets all transactions (vouchers) that are booked on the given id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Receipt id |

**Responses**: `200` [`Accounting.SimplifiedVoucher`](#schema-accounting-simplifiedvoucher)[]

#### `GET /api/Receipt/StateLogs/{id}`

Returns a list of state logs related to given receipt id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Receipt id |

**Responses**: `200` [`EntityStateLog`](#schema-entitystatelog)[]

#### `GET /api/Receipt/CanReceivePayouts`

Checks if the logged in person has registered payment information.

**Responses**: `200` `boolean`

#### `GET /api/Receipt/DimensionSuggestions`

Return mostly used dimensions within last year for logged in user and company/>

**Responses**: `200` `string(uuid)`[]

#### `PUT /api/Receipt/HandleDocumentDraft`

**Body**: [`ReceiptDocumentDraft`](#schema-receiptdocumentdraft)

**Responses**: `200` `integer(int32)`

#### `GET /api/Receipt/WintCardSuppliers`

Return a list of supplier names in WintCard receipts for logged in user and company

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `searchTerm` | query | `string` |  | Search term against supplier name |

**Responses**: `200` `string`[]

#### `GET /api/Receipt/TopWintCardSuppliers`

Return a list of most common supplier names in WintCard receipts for logged in user and company

**Responses**: `200` `string`[]

<a id="tag-reference"></a>
### Reference

#### `GET /api/Reference/{id}`

Returns a reference based on given id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Reference`](#schema-reference)

#### `PUT /api/Reference/{id}`

Updates a reference based on given reference id and data

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Body**: [`ReferencePut`](#schema-referenceput)

**Responses**: `200` `integer(int32)`

#### `DELETE /api/Reference/{id}`

Deletes a reference based on given id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

#### `GET /api/Reference`

Returns a list of references based on given reference filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `CustomerId` | query | `integer(int32)` |  | Customer id |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Reference`](#schema-wint-utils-webapi-listresponseof-reference)

#### `POST /api/Reference`

Creates a new reference based on given reference data

**Body**: [`ReferencePost`](#schema-referencepost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Reference/SearchByName`

Return list of reference persons based on customerId and searchString

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `customerId` | query | `integer(int32)` | yes |  |
| `searchString` | query | `string` |  |  |

**Responses**: `200` [`ReferenceSearchResponse`](#schema-referencesearchresponse)[]

#### `GET /api/Reference/SearchByMail`

Return list of reference persons based on customerId and searchString

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `customerId` | query | `integer(int32)` | yes |  |
| `searchString` | query | `string` |  |  |

**Responses**: `200` [`ReferenceSearchResponse`](#schema-referencesearchresponse)[]

#### `GET /api/Reference/Common`

Return a list of top 5 common Reference persons based on customerId

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `customerId` | query | `integer(int32)` | yes |  |

**Responses**: `200` [`ReferenceSearchResponse`](#schema-referencesearchresponse)[]

<a id="tag-report"></a>
### Report

#### `GET /api/Report`

Get report

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `IncludeDailyTurnover` | query | `boolean` |  | Include daily turnover in report; otherwise monthly |
| `IncludeIBs` | query | `boolean` |  | Include incoming balances |
| `IncludeMonthlyTurnovers` | query | `boolean` |  | Include monthly turnover |
| `StartDate` | query | `string(date-time)` |  | Start date Start date is inclusive, if you the 1st as the first day included, this should be set to the 1st. |
| `EndDate` | query | `string(date-time)` |  | End date End date is not inclusive, ie. if you want the 10th to be the last day included EndDate should be set to the 11th |
| `AccountRanges` | query | `string`[] |  | List of account ranges. Example: 1000<1200,1400<1500-1350 Will include account in range 1000 to 1200 AND 1400 to 1500 but exclude account 1350 |
| `AccountIds` | query | `string(uuid)`[] |  | List of account ids to include |
| `AccountNumbers` | query | `integer(int32)`[] |  | List of account numbers to include |
| `AccountStart` | query | `integer(int32)` |  | Start of account number |
| `AccountEnd` | query | `integer(int32)` |  | End of account number |
| `Dimensions` | query | `string(uuid)`[] |  | List of dimension ids to include |

**Responses**: `200` [`Accounting.Report`](#schema-accounting-report)

<a id="tag-revenuereporting"></a>
### RevenueReporting

#### `GET /api/RevenueReporting/templates`

Get the active revenue reporting templates for the selected company.

Returns the active revenue reporting templates for the currently selected company, including templates that are currently paused. An empty result indicates the company has no active templates, not that it is outside the new revenue reporting flow; whether the company belongs to the new flow at all is given by `RevenueReportingEnabledForCompany` on the company.

**Responses**: `200` [`RevenueReportingTemplate`](#schema-revenuereportingtemplate)[]; `403` No permission

#### `GET /api/RevenueReporting`

Get the submitted revenue reports for the selected company.

Returns the revenue reports submitted on the new revenue reporting templates for the currently selected company. An empty result indicates the company has not submitted any reports on the new flow. Voided reports are only included when the status filter is set to voided.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `TemplateId` | query | `string(uuid)` |  | Include reports created from this template (payment method). |
| `Status` | query | [`RevenueReportStatus`](#schema-revenuereportstatus) |  | Include reports with this status. Voided reports are only included when this is explicitly set to Wint.Superkoll.API.Model.RevenueReportStatus.Voided. |
| `FromDate` | query | `string(date-time)` |  | Include reports with a reporting date on or after this date. |
| `ToDate` | query | `string(date-time)` |  | Include reports with a reporting date on or before this date. |
| `OwnerIds` | query | `integer(int32)`[] |  | Include reports registered by these owners. |
| `MinAmount` | query | `number(double)` |  | Include reports with a total sales amount greater than or equal to this. |
| `MaxAmount` | query | `number(double)` |  | Include reports with a total sales amount less than or equal to this. |
| `MinDifference` | query | `number(double)` |  | Include reports with a difference greater than or equal to this. |
| `MaxDifference` | query | `number(double)` |  | Include reports with a difference less than or equal to this. |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_RevenueReportDescriptor`](#schema-wint-utils-webapi-listresponseof-revenuereportdescriptor); `403` No permission

#### `POST /api/RevenueReporting`

Submit a revenue report for the selected company.

Uploads the report attachments, creates the report in the revenue reporting service, books the accounting voucher and links the voucher back to the report. The template's todo is shown only to users whose roles it names, or a company admin, but submitting is not limited to those users - any user this endpoint permits may report on any active template.

**Body**: [`RevenueReportDto`](#schema-revenuereportdto)

**Responses**: `200` `string(uuid)`; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `GET /api/RevenueReporting/{id}`

Get the full details of a submitted revenue report for the selected company.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |

**Responses**: `200` [`RevenueReportDetail`](#schema-revenuereportdetail); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `GET /api/RevenueReporting/{id}/attachment/{attachmentId}`

Get an attachment (image/PDF) of a submitted revenue report.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |
| `attachmentId` | path | `string` | yes | Identifier of the attachment; the first attachment is returned when omitted. |

**Responses**: `200` [`RevenueReportAttachment`](#schema-revenuereportattachment); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `GET /api/RevenueReporting/{id}/transactions`

Get the booked voucher transactions of a submitted revenue report.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report. |

**Responses**: `200` [`Accounting.SimplifiedVoucher`](#schema-accounting-simplifiedvoucher)[]; `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `POST /api/RevenueReporting/approve`

Approve a revenue reporting period for the selected company.

Approves a monthly period for a template (payment method). When no report was submitted for the period the request must confirm there was no income. Optional attachments supporting the approval ("kompletterande underlag") are uploaded to blob storage, and each one also becomes its own unbooked accounting voucher the accountant handles from the period's Heart todo. Only a user whose roles the template names, or a company admin, may approve for it; the template's todo is hidden from everyone else.

**Body**: [`RevenueReportApproveRequest`](#schema-revenuereportapproverequest)

**Responses**: `200` [`RevenueReportApproval`](#schema-revenuereportapproval); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

#### `GET /api/RevenueReporting/approvals`

Get the revenue reporting period approvals for the selected company.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `templateId` | query | `string(uuid)` |  | Include approvals for this template (payment method). |
| `year` | query | `integer(int32)` |  | Include approvals for this period year. |

**Responses**: `200` [`RevenueReportApproval`](#schema-revenuereportapproval)[]; `403` No permission

#### `GET /api/RevenueReporting/{templateId}/{periodYear}/{periodMonth}/approval-attachment`

Get the attachment (image/PDF) of a revenue reporting period approval.

Serves the customer's own copy of the supplementary material, and only the first file: the approval in the Wint.RevenueReporting service holds one attachment. The accountant reads the same material as unbooked vouchers instead, so this endpoint is only kept for the customer app and for approvals made before those vouchers existed.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `templateId` | path | `string(uuid)` | yes | Identifier of the template (payment method). |
| `periodYear` | path | `integer(int32)` | yes | Period year of the approval. |
| `periodMonth` | path | `integer(int32)` | yes | Period month of the approval. |

**Responses**: `200` [`RevenueReportAttachment`](#schema-revenuereportattachment); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

<a id="tag-salarydeviation"></a>
### SalaryDeviation

#### `GET /api/SalaryDeviation/months`

Get salary deviation months.

Get salary deviation months for a company if salary deviation enabled.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_SalaryDeviationMonth`](#schema-wint-utils-webapi-listresponseof-salarydeviationmonth); `400` Salary deviations is disabled for the logged in company; `403` No permission

#### `GET /api/SalaryDeviation/months/{yearMonth}`

Get a specific salary deviation month.

Get a specific salary deviation month for a company if salary deviation enabled.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `yearMonth` | path | `integer(int32)` | yes | Year and month value (e.g. YYYYMM). |

**Responses**: `200` [`SalaryDeviationMonth`](#schema-salarydeviationmonth); `400` Salary deviations is disabled for the logged in company; `403` No permission; `404` Not found

#### `POST /api/SalaryDeviation/SubmitReport`

Submit a deviation month.

Submit the deviation report for a given year and month

**Body**: [`ReportSubmissionData`](#schema-reportsubmissiondata)

**Responses**: `200` `integer(int32)`; `400` Invalid information; `403` No permission

#### `GET /api/SalaryDeviation`

Get salary deviation list.

Get all salary deviations based on the filter. All employees get their own salary deviations while salary admin gets company's all salary deviations.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `YearAndMonth` | query | `integer(int32)` |  | Year and month e.g. YYYYMM |
| `PersonId` | query | `integer(int32)` |  | Employee Id |
| `Types` | query | [`SalaryDeviationType`](#schema-salarydeviationtype)[] |  | If set will only return deviations of these types |
| `IncludePersonsWithNoDeviations` | query | `boolean` |  | Include persons who does not submit any deviations |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_SalaryDeviationDescriptor`](#schema-wint-utils-webapi-listresponseof-salarydeviationdescriptor); `400` Invalid information; `403` No permission

#### `PUT /api/SalaryDeviation`

Update salary deviation.

Update a salary deviation instance with given data.

**Body**: [`SalaryDeviationPut`](#schema-salarydeviationput)

**Responses**: `200` [`SalaryDeviationPutPostStatus`](#schema-salarydeviationputpoststatus); `500` Server error

#### `GET /api/SalaryDeviation/{id}`

Get salary deviation instance.

Get a specific salary deviations instance for the given id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Unique ID of the salary deviation. |

**Responses**: `200` [`SalaryDeviation`](#schema-salarydeviation); `400` Invalid information; `403` No permission; `404` Not found

#### `DELETE /api/SalaryDeviation/{id}`

Delete salary deviation.

Delete an existing salary deviation with given Id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Id of the salary deviation to be deleted. |

**Responses**: `200` Successful operation; `400` Invalid information; `403` No permission; `404` Not found

#### `POST /api/SalaryDeviation/Create`

Create new salary deviation.

Create new salary deviation instance for given data.

**Body**: [`SalaryDeviationPost`](#schema-salarydeviationpost)

**Responses**: `200` [`SalaryDeviationPutPostStatus`](#schema-salarydeviationputpoststatus); `500` Server error

#### `GET /api/SalaryDeviation/PersonMonthlySalaryDeviations`

Get salary deviations per month per user.

Get all monthly salary deviations based on the filter. All employees get their own salary deviations while salary admin gets company's all salary deviations.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `PersonIds` | query | `integer(int32)`[] |  | Salary deviations that belongs to these persons |
| `YearAndMonthFrom` | query | `integer(int32)` |  | Salary deviations from |
| `YearAndMonthTo` | query | `integer(int32)` |  | Salary deviations to |
| `States` | query | [`SalaryDeviationMonthState`](#schema-salarydeviationmonthstate)[] |  | Salary deviations in monthly states |
| `TotalFrom` | query | `number(double)` |  | Total deviation salary from |
| `TotalTo` | query | `number(double)` |  | Total deviation salary to |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_PersonMonthlySalaryDeviation`](#schema-wint-utils-webapi-listresponseof-personmonthlysalarydeviation)

<a id="tag-salarydrafts"></a>
### SalaryDrafts

#### `GET /api/SalaryDrafts`

Get salary deviation draft list

Filters all salary deviation drafts

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `From` | query | `integer(int32)` |  | From Wint.Superkoll.API.Model.YearAndMonth (YYYYMM, inclusive). |
| `To` | query | `integer(int32)` |  | To Wint.Superkoll.API.Model.YearAndMonth (YYYYMM, inclusive). |
| `State` | query | `integer(int32)` |  | The Wint.Superkoll.API.Model.SalaryDraftState |
| `States` | query | [`SalaryDraftState`](#schema-salarydraftstate)[] |  | Salary drafts in these states |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_SalaryDraft`](#schema-wint-utils-webapi-listresponseof-salarydraft); `400` Invalid information; `403` No permission

#### `GET /api/SalaryDrafts/{id}`

Get salary draft instance

Gets a specific salary draft instance by id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | Unique ID of the salary draft. |

**Responses**: `200` [`SalaryDraft`](#schema-salarydraft)

#### `PUT /api/SalaryDrafts/{id}`

Update a salary draft status or owner

Allows for: - updating the salary draft status by id to approved or rejected status (the latter requiring a reject message) - assigning the draft by id and ownerId to a company salary administrator, who will then be the salary draft todo target

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The resource id |

**Body**: [`SalaryDraftPut`](#schema-salarydraftput)

**Responses**: `200` [`SalaryDraft`](#schema-salarydraft); `400` Invalid information; `403` No permission

#### `GET /api/SalaryDrafts/{id}/attachment/{attachmentId}`

Get a salary draft attachment

Returns a salary draft attachment by draft salary draft id and the attachmentId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the salary draft. |
| `attachmentId` | path | `integer(int32)` | yes | The id of the attachment. |

**Responses**: `200` [`SalaryDraftAttachment`](#schema-salarydraftattachment); `400` Invalid information; `403` No permission

#### `GET /api/SalaryDrafts/{id}/download`

Download salary draft attachments

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the salary draft. |

**Responses**: `200` Successful operation; `400` Invalid information; `403` No permission

#### `POST /api/SalaryDrafts/{id}/Accept`

Approve the salary draft given by the id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the salary draft. |

**Responses**: `200` OK

#### `POST /api/SalaryDrafts/{id}/Reject`

Reject the salary draft given by the id with rejectAction message

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the salary draft. |

**Body**: [`SalaryDraftRejectAction`](#schema-salarydraftrejectaction)

**Responses**: `200` OK

#### `POST /api/SalaryDrafts/{id}/Assign`

Forward the salary draft of given id using the information on assignAction

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes | The id of the salary draft. |

**Body**: [`SalaryDraftAssignAction`](#schema-salarydraftassignaction)

**Responses**: `200` OK

#### `GET /api/SalaryDrafts/SearchSalaryAdmins`

Return list of salary draft assignees according to the given search string

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SearchStr` | query | `string` |  | Search string for salary admin |
| `IncludeSelf` | query | `boolean` |  | Whether needs to include or exclude the current user |

**Responses**: `200` [`SalaryAdminSearchInfo`](#schema-salaryadminsearchinfo)[]

<a id="tag-salaryimport"></a>
### SalaryImport

#### `POST /api/SalaryImport`

A new import file will be created to be handled by Wint

**Body**: [`SalaryImportFile`](#schema-salaryimportfile)

**Responses**: `200` `integer(int32)`

<a id="tag-search"></a>
### Search

#### `GET /api/Search`

Return search results for given search string.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SearchStr` | query | `string` |  | Search text |

**Responses**: `200` [`SearchResponseItems`](#schema-searchresponseitems)[]

<a id="tag-selfinvoice"></a>
### SelfInvoice

#### `GET /api/SelfInvoice`

**Responses**: `200` [`SelfInvoiceResponse`](#schema-selfinvoiceresponse)

#### `POST /api/SelfInvoice`

**Body**: [`SelfInvoiceImageDataPost`](#schema-selfinvoiceimagedatapost)

**Responses**: `200` `string(uuid)`

#### `GET /api/SelfInvoice/id`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | query | `string(uuid)` |  |  |

**Responses**: `200` [`SelfInvoice`](#schema-selfinvoice)

#### `POST /api/SelfInvoice/{id}/mark-rejected`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` OK

#### `POST /api/SelfInvoice/{id}/mark-created`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` OK

#### `GET /api/SelfInvoice/{id}/template-invoice`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` [`Invoice`](#schema-invoice)

#### `GET /api/SelfInvoice/{id}/customer-invoice-id`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` `integer(int32)`

<a id="tag-series"></a>
### Series

#### `GET /api/Series`

Filter series

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Name` | query | `string` |  | Name of series to include |
| `IncludeImportSeries` | query | `boolean` |  | Include series used for import only |
| `ExactShortName` | query | `string` |  | Exact short name of series to be included |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Accounting.Series`](#schema-wint-utils-webapi-listresponseof-accounting-series)

<a id="tag-support"></a>
### Support

#### `GET /api/Support/{issueId}/Comments`

Returns a Wint.Utils.WebApi.ListResponse`1 with filtered comments from the support issue corresponding to the given issueId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The support issue id. |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_SupportComment`](#schema-wint-utils-webapi-listresponseof-supportcomment)

#### `POST /api/Support/{issueId}/Comments`

Adds a comment to the support issue corresponding to the given issueId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the support issue. |

**Body**: [`SupportCommentPost`](#schema-supportcommentpost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Support/{issueId}/Attachments/{attachmentId}`

Returns an attachment corresponding to the given attachmentId that is associated with the given issueId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the support issue. |
| `attachmentId` | path | `integer(int32)` | yes | The id of the attachment. |

**Responses**: `200` [`SupportAttachment`](#schema-supportattachment)

#### `GET /api/Support/{issueId}/Attachments/{attachmentId}/Image`

Returns a streamed data result of the attachment corresponding to the given attachmentId as an image format. If the attachment is of type application/pdf, the pdf will be converted to image/png.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the support issue. |
| `attachmentId` | path | `integer(int32)` | yes | The id of the attachment. |
| `page` | query | `integer(int32)` |  | The page which should be returned. Relevant if the attachment is of type application/pdf. The page is zero-based. |

**Responses**: `200` OK

#### `GET /api/Support/{issueId}/DownloadAttachment/{attachmentId}`

Returns a streamed data result of the attachment corresponding to the given attachmentId

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the support issue. |
| `attachmentId` | path | `integer(int32)` | yes | The id of the attachment. |

**Responses**: `200` OK

#### `GET /api/Support/{issueId}/Attachments/{attachmentId}/Pages`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes |  |
| `attachmentId` | path | `integer(int32)` | yes |  |

**Responses**: `200` `integer(int32)`

#### `GET /api/Support/{issueId}`

Returns the issue corresponding to the given issueId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the support issue. |

**Responses**: `200` [`SupportIssue`](#schema-supportissue)

#### `GET /api/Support`

Returns a Wint.Utils.WebApi.ListResponse`1 of filtered errands.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `States` | query | [`SupportIssueState`](#schema-supportissuestate)[] |  | The states the filtered issues should have. If states is empty, all issues will be returned. |
| `Severities` | query | [`SupportIssueSeverity`](#schema-supportissueseverity)[] |  | The severities the filtered issues should have. |
| `UserIds` | query | `integer(int32)`[] |  | Find only issues created by this user. |
| `SearchString` | query | `string` |  | Free text search on support issues. |
| `CreatedDateFrom` | query | `string(date-time)` |  | Find all issues created after this date |
| `CreatedDateTo` | query | `string(date-time)` |  | Find all issues created before this date |
| `LastUpdatedFrom` | query | `string(date-time)` |  | Find all issues last updated after this date |
| `LastUpdatedTo` | query | `string(date-time)` |  | Find all issues last updated before this date |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_SupportIssue`](#schema-wint-utils-webapi-listresponseof-supportissue)

#### `POST /api/Support`

Creates the given issue.

**Body**: [`SupportIssuePost`](#schema-supportissuepost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Support/ListItems`

Returns a Wint.Utils.WebApi.ListResponse`1 of filtered errands.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `States` | query | [`SupportIssueState`](#schema-supportissuestate)[] |  | The states the filtered issues should have. If states is empty, all issues will be returned. |
| `Severities` | query | [`SupportIssueSeverity`](#schema-supportissueseverity)[] |  | The severities the filtered issues should have. |
| `UserIds` | query | `integer(int32)`[] |  | Find only issues created by this user. |
| `SearchString` | query | `string` |  | Free text search on support issues. |
| `CreatedDateFrom` | query | `string(date-time)` |  | Find all issues created after this date |
| `CreatedDateTo` | query | `string(date-time)` |  | Find all issues created before this date |
| `LastUpdatedFrom` | query | `string(date-time)` |  | Find all issues last updated after this date |
| `LastUpdatedTo` | query | `string(date-time)` |  | Find all issues last updated before this date |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_SupportIssueListItem`](#schema-wint-utils-webapi-listresponseof-supportissuelistitem)

#### `POST /api/Support/{issueId}/Resolve`

Sets the issue corresponding to the given issueId to resolved.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the issue. |

**Responses**: `200` OK

#### `POST /api/Support/{issueId}/Unresolve`

Sets the issue corresponding to the given issueId to unresolved.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the issue. |

**Responses**: `200` OK

#### `POST /api/Support/{issueId}/SendTo/{employeeId}`

Sends the issue corresponding to the given issueId to the employee corresponding to the given employeeId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the issue. |
| `employeeId` | path | `integer(int32)` | yes | The id of the employee. |

**Responses**: `200` OK

#### `POST /api/Support/{issueId}/AgencyForward`

Forwards the byrå-stamped issue corresponding to the given issueId to Wint or to a specific colleague at the same byrå. The Byråsupport replacement for M:Wint.Superkoll.API.Site.Controllers.SupportController.SendToAsync(System.Int32,System.Int32) on a stamped issue.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the issue. |

**Body**: [`AgencyForwardTarget`](#schema-agencyforwardtarget)

**Responses**: `200` OK

#### `GET /api/Support/{issueId}/AgencyForwardTargets`

Returns the byrå colleagues the issue corresponding to the given issueId may be forwarded to via M:Wint.Superkoll.API.Site.Controllers.SupportController.AgencyForwardAsync(System.Int32,Wint.Superkoll.API.Model.AgencyForwardTarget).

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the issue. |

**Responses**: `200` [`User`](#schema-user)[]

#### `POST /api/Support/{issueId}/Confirm`

Confirms the issue corresponding to the given issueId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `issueId` | path | `integer(int32)` | yes | The id of the issue. |

**Responses**: `200` OK

#### `GET /api/Support/CustomerCase/Post/{commentId}/Rating`

Gets the rating of the issue comment corresponding to the given commentId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `commentId` | path | `integer(int32)` | yes | The id of the comment. |

**Responses**: `200` [`SupportCommentRating`](#schema-supportcommentrating)

#### `POST /api/Support/CustomerCase/Post/{commentId}/Rating`

Sets the rating of the issue comment corresponding to the given commentId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `commentId` | path | `integer(int32)` | yes | The id of the comment. |

**Body**: [`SupportCommentRatingPost`](#schema-supportcommentratingpost)

**Responses**: `200` OK

#### `DELETE /api/Support/CustomerCase/Post/{commentId}/Rating`

Deletes the rating of the issue comment corresponding to the given commentId.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `commentId` | path | `integer(int32)` | yes | The id of the comment. |

**Responses**: `200` OK

#### `GET /api/Support/GetSuggestedSupportPersons`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Count` | query | `integer(int32)` |  | The max number of persons to be fetched |

**Responses**: `200` [`SupportSuggestedPersonsCollection`](#schema-supportsuggestedpersonscollection)

<a id="tag-supportagent"></a>
### SupportAgent

#### `POST /api/SupportAgent/Sessions`

Opens a session.

**Responses**: `200` [`Wint.Support.Service.Model.Agent.AgentSessionCreated`](#schema-wint-support-service-model-agent-agentsessioncreated)

#### `POST /api/SupportAgent/Sessions/{sessionId}/Messages`

Sends one customer message and returns the single reply it produced.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `sessionId` | path | `string(uuid)` | yes |  |

**Body**: [`Wint.Support.Service.Model.Agent.AgentMessageRequest`](#schema-wint-support-service-model-agent-agentmessagerequest)

**Responses**: `200` [`Wint.Support.Service.Model.Agent.AgentReply`](#schema-wint-support-service-model-agent-agentreply)

#### `POST /api/SupportAgent/Sessions/{sessionId}/Case`

Files the case the agent drafted.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `sessionId` | path | `string(uuid)` | yes |  |

**Body**: [`Wint.Support.Service.Model.Agent.AgentCaseRequest`](#schema-wint-support-service-model-agent-agentcaserequest)

**Responses**: `200` [`Wint.Support.Service.Model.Agent.AgentCaseCreated`](#schema-wint-support-service-model-agent-agentcasecreated)

#### `POST /api/SupportAgent/Sessions/{sessionId}/CaseSummary`

What the in-chat support card opens with: subject, summary, category and the facts for support. Sends nothing - the case itself goes through `api/Support`, as from the form.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `sessionId` | path | `string(uuid)` | yes |  |

**Body**: [`Wint.Support.Service.Model.Agent.AgentCaseSummaryRequest`](#schema-wint-support-service-model-agent-agentcasesummaryrequest)

**Responses**: `200` [`Wint.Support.Service.Model.Agent.AgentCaseSummary`](#schema-wint-support-service-model-agent-agentcasesummary)

<a id="tag-survey"></a>
### Survey

#### `GET /api/Survey/{id}`

Returns a Wint.Superkoll.API.Model.Surveys.Survey for the specific id id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Id of survey to fetch |

**Responses**: `200` [`Surveys.Survey`](#schema-surveys-survey)

#### `POST /api/Survey/surveyResponses`

Saves a Wint.Superkoll.API.Model.Surveys.SurveyResponseInputModel.

**Body**: [`Surveys.SurveyResponseInputModel`](#schema-surveys-surveyresponseinputmodel)

**Responses**: `200` OK

#### `GET /api/Survey/{id}/Status`

Return a Wint.Superkoll.API.Model.Surveys.SurveyStatus for the specific id id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` [`Surveys.SurveyStatus`](#schema-surveys-surveystatus)

#### `PUT /api/Survey/{id}/SurveyCustomerCase`

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string` | yes |  |

**Responses**: `200` OK

#### `POST /api/Survey/{id}/comments`

Add a survey comment

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | SurveyId |

**Body**: [`Surveys.SurveyCommentRequest`](#schema-surveys-surveycommentrequest)

**Responses**: `200` [`Surveys.SurveyComment`](#schema-surveys-surveycomment)

#### `PUT /api/Survey/{id}/send`

Assigns survey to another person

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Body**: [`Surveys.SurveySendToPersonAction`](#schema-surveys-surveysendtopersonaction)

**Responses**: `200` OK

#### `GET /api/Survey/GetSurveyPersons`

Returns persons eligable to surveys

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `SearchStr` | query | `string` |  | Search string for invoice person name |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-listresponseof-wint-utils-webapi-searchresult)

#### `GET /api/Survey/GetSurveyPersonSuggestions`

returns persons eligable to surveys

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Count` | query | `integer(int32)` |  | number of max persons to be fetched |

**Responses**: `200` [`Surveys.SurveyPersonsSuggestionCollection`](#schema-surveys-surveypersonssuggestioncollection)

#### `GET /api/Survey/attachment/{id}`

Get the survey attachment which is associate with the given id.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Unique ID for a survey attachment. |

**Responses**: `200` [`Surveys.SurveyAttachment`](#schema-surveys-surveyattachment)

<a id="tag-timereport"></a>
### TimeReport

#### `GET /api/TimeReport/Report`

Gets a list of filtered time reports

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `ProjectId` | query | `string(uuid)` |  | Id for the time reporting project |
| `BusinessUnitId` | query | `string(uuid)` |  | Id for the business unit |
| `BusinessUnitManagerId` | query | `integer(int32)` |  | Business unit manager id |
| `PersonId` | query | `integer(int32)` |  | Id for the employee |
| `FromDate` | query | `string(date-time)` |  | From Date |
| `ToDate` | query | `string(date-time)` |  | To Date |
| `ExcludeInvoiced` | query | `boolean` |  | Exclude invoiced records |
| `CategoryId` | query | `integer(int32)` |  | Id for project category |
| `OnlyIncludeHourlyIndividualBillingModel` | query | `boolean` |  | When true only data for hourly |
| `IncludeAllEmployees` | query | `boolean` |  | Includes persons without salary settings or reported time if they have the employee flag set (and not auditor) |
| `IncludeOnlyDeviations` | query | `boolean` |  | Includes only deviations |

**Responses**: `200` [`TimeReporting.TimeReportingReportRow`](#schema-timereporting-timereportingreportrow)[]; `400` Bad request; `403` No permission

#### `GET /api/TimeReport/Export`

Creates and exports a list of time reports Exporting is done through exporting a class called TimeReportingExportRow

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `ProjectId` | query | `string(uuid)` |  | Id for the time reporting project |
| `BusinessUnitId` | query | `string(uuid)` |  | Id for the business unit |
| `BusinessUnitManagerId` | query | `integer(int32)` |  | Business unit manager id |
| `PersonId` | query | `integer(int32)` |  | Id for the employee |
| `FromDate` | query | `string(date-time)` |  | From Date |
| `ToDate` | query | `string(date-time)` |  | To Date |
| `ExcludeInvoiced` | query | `boolean` |  | Exclude invoiced records |
| `CategoryId` | query | `integer(int32)` |  | Id for project category |
| `OnlyIncludeHourlyIndividualBillingModel` | query | `boolean` |  | When true only data for hourly |
| `IncludeAllEmployees` | query | `boolean` |  | Includes persons without salary settings or reported time if they have the employee flag set (and not auditor) |
| `IncludeOnlyDeviations` | query | `boolean` |  | Includes only deviations |

**Responses**: `200` [`TimeReporting.TimeReportingExportRow`](#schema-timereporting-timereportingexportrow)[]; `400` Bad request; `403` No permission

#### `GET /api/TimeReport/Status`

If all are attested the attested status will be returned. If all are attested or locked the locked status will be returned. If some time report in that range has created status the created status will be returned.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `employeeId` | query | `integer(int32)` |  |  |
| `startDate` | query | `string(date-time)` |  |  |
| `endDate` | query | `string(date-time)` |  |  |

**Responses**: `200` [`TimeReporting.TimeReportStatus`](#schema-timereporting-timereportstatus)

<a id="tag-transaction"></a>
### Transaction

#### `GET /api/Transaction`

Filter Transactions

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `IncludeUB` | query | `boolean` |  | Include outgoing balance |
| `IBBookingDateStart` | query | `boolean` |  |  |
| `AccountRange` | query | `string` |  | Account range. Example: 1000<1200,1400<1500-1350 Will include account in range 1000 to 1200 AND 1400 to 1500 but exclude account 1350 |
| `AccountStart` | query | `integer(int32)` |  | Start of account number |
| `AccountEnd` | query | `integer(int32)` |  | End of account number |
| `VoucherId` | query | `string(uuid)` |  | Voucher Id |
| `IncludeDeletedTransactions` | query | `boolean` |  | Include deleted transactions |
| `Checked` | query | `boolean` |  |  |
| `MinAmount` | query | `number(double)` |  | Minimum amount to include |
| `MaxAmount` | query | `number(double)` |  | Maximum amount to include |
| `VoucherNumberStart` | query | `integer(int32)` |  | Start of voucher number |
| `VoucherNumberEnd` | query | `integer(int32)` |  | End of voucher number |
| `Series` | query | `string(uuid)`[] |  | List of series ids to include |
| `Dimensions` | query | `string(uuid)`[] |  | List of dimension ids to include |
| `BookingDateStart` | query | `string(date-time)` |  | Start of booking date |
| `BookingDateEnd` | query | `string(date-time)` |  | End of booking date |
| `Text` | query | `string` |  | Text to filter on |
| `Accounts` | query | `string(uuid)`[] |  | List of account ids to include |
| `AccountNumbers` | query | `integer(int32)`[] |  | List of account numbers |
| `Type` | query | [`ShowVoucherTypes`](#schema-showvouchertypes) |  | Voucher type |
| `MissingReference` | query | `boolean` |  | Include only transactions with missing reference |
| `ReferenceType` | query | `string` |  | Reference type to include |
| `IncludeVoucher` | query | `boolean` |  | Include voucher information |
| `CategoryId` | query | `integer(int32)` |  | Transaction Category |
| `UseAuditCategories` | query | `boolean` |  | Interpret Wint.Superkoll.API.Model.Accounting.TransactionFilter.CategoryId as a value of Wint.Model.Enums.AuditCategories |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Accounting.Transaction`](#schema-wint-utils-webapi-listresponseof-accounting-transaction)

#### `GET /api/Transaction/Series`

**Responses**: `200` [`Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-searchresult)[]

#### `GET /api/Transaction/Categories`

**Responses**: `200` [`Accounting.Category`](#schema-accounting-category)[]

<a id="tag-unit"></a>
### Unit

#### `GET /api/Unit`

Returns a list of units based on given unit filter

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Unit`](#schema-wint-utils-webapi-listresponseof-unit)

#### `POST /api/Unit`

Creates a unit based on given unit data

**Body**: [`UnitPost`](#schema-unitpost)

**Responses**: `200` `integer(int32)`

#### `GET /api/Unit/{id}`

Returns a unit based on given id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`Unit`](#schema-unit)

#### `DELETE /api/Unit/{id}`

Delete a unit based on given id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `integer(int32)` | yes |  |

**Responses**: `200` OK

<a id="tag-userapikey"></a>
### UserApiKey

#### `DELETE /api/auth/key`

Revokes the user API key this request is authenticated with. The key stops working immediately. Also evicts a key that was already deactivated in the database but still authenticates from the cache.

**Responses**: `200` OK

#### `DELETE /api/auth/keys`

Revokes every user API key belonging to the authenticated user, including the one in use.

**Responses**: `200` OK

<a id="tag-vatreports"></a>
### VatReports

#### `GET /api/VatReports/Available`

Whether the selected company has VAT reports to show the signed-in advisor.

The web app asks this before showing its shortcut. 403 for a non-advisor means "do not show it"; `available` is false for a company without an external agency or without Wint Accounting.

**Responses**: `200` [`VatReportsAvailability`](#schema-vatreportsavailability); `403` No permission

#### `GET /api/VatReports`

List the selected company's VAT reports, newest period first.

Corrections included. 0-based `page`; `numPerPage` is at most 12, because each row reads its box 49 from Wint Accounting. A company the reports are not available for gets an empty list.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_VatReportSummary`](#schema-wint-utils-webapi-listresponseof-vatreportsummary); `403` No permission

#### `GET /api/VatReports/{id}`

Get one VAT report with every box of the declaration.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Identifier of the report in Wint Accounting. |

**Responses**: `200` [`VatReportDetails`](#schema-vatreportdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` No permission

<a id="tag-voucher"></a>
### Voucher

#### `GET /api/Voucher/{id}`

Returns a voucher based on given voucher id

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` [`Accounting.Voucher`](#schema-accounting-voucher)

#### `DELETE /api/Voucher/{id}`

Deletes a voucher

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Id of voucher |

**Responses**: `200` OK

#### `GET /api/Voucher`

List vouchers

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `ImportNumber` | query | `string` |  | Import number |
| `ImportSeries` | query | `string` |  | Import series |
| `ReferenceId` | query | `string` |  | Reference Id |
| `ReferenceType` | query | `string` |  | Reference Type |
| `ReferenceIds` | query | `string`[] |  | List of Reference Ids to include |
| `MissingReference` | query | `boolean` |  | Has missing reference |
| `Type` | query | [`ShowVoucherTypes`](#schema-showvouchertypes) |  | Type of voucher |
| `VoucherNumberMin` | query | `integer(int32)` |  | Voucher minimum number |
| `VoucherNumberMax` | query | `integer(int32)` |  | Voucher maximum nunmber |
| `SeriesShortName` | query | `string` |  | Series short name to include |
| `Series` | query | `string(uuid)`[] |  | List of series ids to include |
| `BookingDateStart` | query | `string(date-time)` |  | Start of booking date |
| `BookingDateEnd` | query | `string(date-time)` |  | End of booking date |
| `Text` | query | `string` |  | Text of voucher to include |
| `Accounts` | query | `string(uuid)`[] |  | List of accounts to be included |
| `IncludeTransactions` | query | `boolean` |  | Include transactions in data |
| `ImportId` | query | `string(uuid)` |  | Import Id |
| `CreatedFrom` | query | `string(date-time)` |  | Created from |
| `CreatedBefore` | query | `string(date-time)` |  | Created to |
| `IncludeNumTransactions` | query | `boolean` |  | Include number of transactions |
| `Page` | query | `integer(int32)` |  |  |
| `NumPerPage` | query | `integer(int32)` |  |  |
| `OrderByProperty` | query | `string` |  |  |
| `OrderByDescending` | query | `boolean` |  |  |
| `ThenByProperty` | query | `string` |  |  |
| `ThenByDescending` | query | `boolean` |  |  |
| `IsAutoPaginating` | query | `boolean` |  |  |
| `IncludeSummary` | query | `boolean` |  |  |

**Responses**: `200` [`Wint.Utils.WebApi.ListResponseOf_Accounting.Voucher`](#schema-wint-utils-webapi-listresponseof-accounting-voucher)

#### `POST /api/Voucher`

Creates a voucher

**Body**: [`Accounting.VoucherPost`](#schema-accounting-voucherpost)

**Responses**: `200` `string(uuid)`

<a id="tag-voucherimages"></a>
### VoucherImages

#### `GET /api/VoucherImages/{id}`

Get voucher image

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Id of VoucherImage |

**Responses**: `200` [`Accounting.VoucherImage`](#schema-accounting-voucherimage)

#### `DELETE /api/VoucherImages/{id}`

Delete VoucherImage (will be marked as removed)

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes |  |

**Responses**: `200` OK

#### `POST /api/VoucherImages`

Create VoucherImage

**Body**: [`Accounting.VoucherImagePost`](#schema-accounting-voucherimagepost)

**Responses**: `200` `string(uuid)`

#### `GET /api/VoucherImages/{id}/DownloadPDF`

Download the voucher attachments as PDF

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `id` | path | `string(uuid)` | yes | Voucher id |

**Responses**: `200` OK

<a id="tag-wintsalarydeviation"></a>
### WintSalaryDeviation

#### `GET /api/WintSalaryDeviation/DeviationTypes`

Fetches salary deviation types based on the provided filter criteria.

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own deviations, a business-unit manager with salary rights their unit's, a salary or deviation admin everyone's.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `Name` | query | `string` |  | Gets or sets the name of the salary deviation type filter. |
| `Categories` | query | [`WintSalary.Deviations.SalaryDeviationTypeCategory`](#schema-wintsalary-deviations-salarydeviationtypecategory)[] |  | Gets or sets the categories to filter salary deviations by. |
| `PersonExternalId` | query | `integer(int32)` |  | When set, scopes the returned deviation types to this employee (person external id). Forwarded to Wint.Salary, which narrows the list to the employee's template group and hides vacation types when the employee has no vacation. Null lists the company-level types (e.g. admin browsing). |

**Responses**: `200` [`WintSalary.Deviations.SalaryDeviationType`](#schema-wintsalary-deviations-salarydeviationtype)[]; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `POST /api/WintSalaryDeviation/mutable`

Creates a new salary deviation and returns re-approval information.

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own deviations, a business-unit manager with salary rights their unit's, a salary or deviation admin everyone's. Not idempotent: a repeated request creates another deviation, or is rejected for overlapping the first one. After a timeout or a lost response, list the person's deviations before retrying to see whether the first request went through. Parental-leave types need a `ChildId` from `persons/{personId}/children`.

**Body**: [`WintSalary.Deviations.SalaryDeviationCreateRequest`](#schema-wintsalary-deviations-salarydeviationcreaterequest)

**Responses**: `200` [`WintSalary.SalaryMonthMutationResultOf_System.Guid`](#schema-wintsalary-salarymonthmutationresultof-system-guid); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `PUT /api/WintSalaryDeviation/mutable/{deviationId}`

Updates an existing salary deviation and returns re-approval information.

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own deviations, a business-unit manager with salary rights their unit's, a salary or deviation admin everyone's.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `deviationId` | path | `string(uuid)` | yes | Salary deviation Id |

**Body**: [`WintSalary.Deviations.SalaryDeviationUpdateRequest`](#schema-wintsalary-deviations-salarydeviationupdaterequest)

**Responses**: `200` [`WintSalary.SalaryMonthMutationResultBase`](#schema-wintsalary-salarymonthmutationresultbase); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `DELETE /api/WintSalaryDeviation/mutable/{deviationId}`

Deletes an existing salary deviation and returns re-approval information. A deviation is stored as one period per calendar month its dates fall in; without `yearMonth` the whole deviation is deleted, with it only the periods of that month (or of the range up to `yearMonthTo`).

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own deviations, a business-unit manager with salary rights their unit's, a salary or deviation admin everyone's.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `deviationId` | path | `string(uuid)` | yes | Salary deviation Id |
| `yearMonth` | query | `integer(int32)` |  | Calendar month (YYYYMM) of the first period to delete - the month the dates fall in, not the salary month. Omit to delete the whole deviation. |
| `yearMonthTo` | query | `integer(int32)` |  | Last month (YYYYMM) of the range to delete; requires `yearMonth`. |

**Responses**: `200` [`WintSalary.SalaryMonthMutationResultBase`](#schema-wintsalary-salarymonthmutationresultbase); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `GET /api/WintSalaryDeviation`

Fetches salary deviations based on filter

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own deviations, a business-unit manager with salary rights their unit's, a salary or deviation admin everyone's. Without `PersonId`, an admin gets every employee's deviations and anyone else their own; a `PersonId` the caller may not manage gets 403.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `YearMonth` | query | `integer(int32)` |  | Calendar month (YYYYMM) the deviation's dates fall in, not the salary month it is paid in. Returns the deviations whose dates overlap that month, each cut down to that month's part (`FullDeviationLoaded` is false when the deviation also spans other months). Omit to get every deviation in full. |
| `PersonId` | query | `integer(int32)` |  | Unique identifier for the person to filter salary deviations. |
| `DeviationTypeIds` | query | `string(uuid)`[] |  | Salary deviation types to be filtered. |

**Responses**: `200` [`WintSalary.Deviations.SalaryDeviation`](#schema-wintsalary-deviations-salarydeviation)[]; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `GET /api/WintSalaryDeviation/{deviationId}`

Fetches a salary deviation by its ID for the specified optional year-month range. A deviation is stored as one period per calendar month its dates fall in. Without `yearMonth` the whole deviation is returned; with it, the dates, value and state describe only the selected months (`FullDeviationLoaded` is then false if there are others), and a month with no period gives 404.

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own deviations, a business-unit manager with salary rights their unit's, a salary or deviation admin everyone's.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `deviationId` | path | `string(uuid)` | yes | Salary deviation Id |
| `yearMonth` | query | `integer(int32)` |  | Calendar month (YYYYMM) to select - the month the dates fall in, not the salary month. Omit for the whole deviation. |
| `yearMonthTo` | query | `integer(int32)` |  | Last month (YYYYMM) of a range to select; requires `yearMonth`. |

**Responses**: `200` [`WintSalary.Deviations.SalaryDeviation`](#schema-wintsalary-deviations-salarydeviation); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `GET /api/WintSalaryDeviation/persons/{personId}/children`

Retrieves the list of children for a specific person.

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own children, a business-unit manager with salary rights those of their unit, a salary or deviation admin everyone's.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `personId` | path | `integer(int32)` | yes |  |

**Responses**: `200` [`WintSalary.Deviations.Child`](#schema-wintsalary-deviations-child)[]; `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

#### `POST /api/WintSalaryDeviation/persons/{personId}/children`

Creates a new child for a specific person.

For companies on Wint Lön; any other company, including one whose activation is pending, gets 400 `WintSalaryIsNotActivated` (deviation-reporting companies use `api/SalaryDeviation`). Acts with the permissions of the person the credentials belong to: an employee reaches their own children, a business-unit manager with salary rights those of their unit, a salary or deviation admin everyone's.

| Param | In | Type | Req | Description |
|---|---|---|---|---|
| `personId` | path | `integer(int32)` | yes | Person external Id |

**Body**: [`WintSalary.Deviations.ChildForCreate`](#schema-wintsalary-deviations-childforcreate)

**Responses**: `200` [`WintSalary.Deviations.Child`](#schema-wintsalary-deviations-child); `400` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `403` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails); `404` [`Microsoft.AspNetCore.Mvc.ProblemDetails`](#schema-microsoft-aspnetcore-mvc-problemdetails)

## Schemas

Field types use the spec's PascalCase property names (the JSON wire format). `?` marks nullable fields. Enums accept the string name; the integer value is shown for reference.

<a id="schema-accounting-account"></a>
#### `Accounting.Account`

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Account Id |
| `Name`? | `string` | Account Name |
| `Ib` | `number(double)` | Incoming balance |
| `Number` | `integer(int32)` | Account number |
| `SRU` | `integer(int32)` | SRU-number |
| `LockedTo`? | `string(date-time)` | Account locked from bookkeeping until this date |

<a id="schema-accounting-accountbalance"></a>
#### `Accounting.AccountBalance`

| Field | Type | Description |
|---|---|---|
| `Balance` | `number(double)` | Account balance |

<a id="schema-accounting-accountinfo"></a>
#### `Accounting.AccountInfo`

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Account id |
| `Number` | `integer(int32)` | Account number |
| `Description`? | `string` | Account description |

<a id="schema-accounting-category"></a>
#### `Accounting.Category`

Accounting category

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Category Id |
| `Name`? | `string` | Category name |
| `Description`? | `string` | Category description |
| `AccountRangeText`? | `string` | Account range description |

<a id="schema-accounting-dailyturnover"></a>
#### `Accounting.DailyTurnover`

| Field | Type | Description |
|---|---|---|
| `Day` | `string(date-time)` | Day |
| `Account` | [`Accounting.AccountInfo`](#schema-accounting-accountinfo) |  |
| `Amount` | `number(double)` | Amount |

<a id="schema-accounting-dimensionreport"></a>
#### `Accounting.DimensionReport`

| Field | Type | Description |
|---|---|---|
| `Dimensions`? | [`Accounting.DimensionReportDimension`](#schema-accounting-dimensionreportdimension)[] | List of dimension requests |

<a id="schema-accounting-dimensionreportaccountdata"></a>
#### `Accounting.DimensionReportAccountData`

| Field | Type | Description |
|---|---|---|
| `AccountNumber` | `integer(int32)` | Account number |
| `AccountId` | `string(uuid)` | Account id |
| `AccountDescription`? | `string` | Account Description |
| `Year` | `integer(int32)` | Year |
| `Month` | `integer(int32)` | Month |
| `Amount` | `number(double)` | Amount |

<a id="schema-accounting-dimensionreportdimension"></a>
#### `Accounting.DimensionReportDimension`

| Field | Type | Description |
|---|---|---|
| `DimensionId` | `string(uuid)` | Dimension Id |
| `Name`? | `string` |  |
| `ShortName`? | `string` | Short name of dimension |
| `TypeName`? | `string` | Dimension Type name |
| `Data`? | [`Accounting.DimensionReportAccountData`](#schema-accounting-dimensionreportaccountdata)[] | List of Dimension Report Account data to include in report |

<a id="schema-accounting-monthlyib"></a>
#### `Accounting.MonthlyIb`

| Field | Type | Description |
|---|---|---|
| `Amount` | `number(double)` | Amount |
| `Account` | [`Accounting.AccountInfo`](#schema-accounting-accountinfo) |  |

<a id="schema-accounting-monthlyturnover"></a>
#### `Accounting.MonthlyTurnover`

| Field | Type | Description |
|---|---|---|
| `YearMonth` | `integer(int32)` | Year and month, yyyyMM |
| `Account` | [`Accounting.AccountInfo`](#schema-accounting-accountinfo) |  |
| `Amount` | `number(double)` | Amount |

<a id="schema-accounting-report"></a>
#### `Accounting.Report`

| Field | Type | Description |
|---|---|---|
| `Turnover`? | [`Accounting.MonthlyTurnover`](#schema-accounting-monthlyturnover)[] | Turnover |
| `DailyTurnover`? | [`Accounting.DailyTurnover`](#schema-accounting-dailyturnover)[] | Turnover, daily |
| `Ibs`? | [`Accounting.MonthlyIb`](#schema-accounting-monthlyib)[] | Incoming ibs |

<a id="schema-accounting-revenueaccountoption"></a>
#### `Accounting.RevenueAccountOption`

| Field | Type | Description |
|---|---|---|
| `Vat` | `number(double)` | The VAT rate (0, 6, 12 or 25) this account is selectable for. |
| `Number` | `integer(int32)` | Account number. |
| `Name`? | `string` | Account name from the chart of accounts. |

<a id="schema-accounting-revenueaccountsresponse"></a>
#### `Accounting.RevenueAccountsResponse`

Data for the article form's revenue account picker.

| Field | Type | Description |
|---|---|---|
| `Enabled` | `boolean` | Whether custom revenue accounts per article are enabled for the company. |
| `Accounts`? | [`Accounting.RevenueAccountOption`](#schema-accounting-revenueaccountoption)[] | The selectable accounts: the Heart-configured intervals per VAT rate, intersected with the company's active chart of accounts. |

<a id="schema-accounting-series"></a>
#### `Accounting.Series`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Name of series |
| `ShortName`? | `string` | Short name of series |
| `Id` | `string(uuid)` | Series Id |

<a id="schema-accounting-simplifiedtransaction"></a>
#### `Accounting.SimplifiedTransaction`

Represent a simplified version of transaction of voucher.

| Field | Type | Description |
|---|---|---|
| `Account` | `integer(int32)` | Account of the transaction. |
| `AccountName`? | `string` | Account name of the transaction. |
| `Amount` | `number(double)` | Amount of the transaction. |
| `Text`? | `string` | Transaction text for the transaction. |
| `Dimensions`? | `string`[] | Dimensions for the transaction. |

<a id="schema-accounting-simplifiedvoucher"></a>
#### `Accounting.SimplifiedVoucher`

Represent the simplified version of voucher information.

| Field | Type | Description |
|---|---|---|
| `Series`? | `string` | Series of the voucher. |
| `VoucherNumber` | `integer(int32)` | Voucher number. |
| `Text`? | `string` | The text of the voucher. |
| `BookingDate` | `string(date-time)` | The booking date of the voucher. |
| `OriginalCurrency`? | `string` | The original currency of the voucher. |
| `Currency`? | `string` | Currency of the voucher. |
| `Transactions`? | [`Accounting.SimplifiedTransaction`](#schema-accounting-simplifiedtransaction)[] | Transactions belongs to voucher. |

<a id="schema-accounting-transaction"></a>
#### `Accounting.Transaction`

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Transaction Id |
| `VoucherId` | `string(uuid)` | Voucher Id |
| `AccountNumber` | `integer(int32)` | Account number |
| `AccountName`? | `string` | Account name |
| `VoucherText`? | `string` | Voucher text |
| `VoucherSeriesName`? | `string` | Voucher series name |
| `VoucherSeriesShortName`? | `string` | Voucher series short name |
| `VoucherNumber` | `integer(int32)` | Voucher number |
| `Amount` | `number(double)` | Transaction amount |
| `Text`? | `string` | Transaction text |
| `BookingDate` | `string(date-time)` | Booking date |
| `AccountId` | `string(uuid)` | Account Id |
| `Dimensions`? | [`Dimension`](#schema-dimension)[] | Dimensions |
| `OriginalAmount`? | `number(double)` | Original amount if not SEK |
| `VoucherReferenceId`? | `integer(int32)` | Reference Id of the voucher |
| `VoucherReferenceType` | [`Accounting.VoucherType`](#schema-accounting-vouchertype) |  |
| `CorrespondentName`? | `string` | Name of the Sender/Recipient |
| `CorrespondentId`? | `integer(int32)` | Id of the Sender/Recipient |

<a id="schema-accounting-transactionpost"></a>
#### `Accounting.TransactionPost`

| Field | Type | Description |
|---|---|---|
| `Amount` | `number(double)` | Transaction amount |
| `Text`? | `string` | Transaction text |
| `AccountId` | `string(uuid)` | Account Id |
| `OriginalAmount`? | `number(double)` | Original amount (if other than SEK) |
| `Dimensions`? | `string(uuid)`[] | List of dimensions |
| `AccountNumber`? | `integer(int32)` | Account number of transaction |

<a id="schema-accounting-voucher"></a>
#### `Accounting.Voucher`

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Voucher Id |
| `Created` | `string(date-time)` | Created date |
| `CreatedById`? | `integer(int32)` | Created By |
| `Deleted` | `boolean` | Is deleted |
| `Number` | `integer(int32)` | Voucher number |
| `Text`? | `string` | Voucher text |
| `BookingDate` | `string(date-time)` | Voucher booking date |
| `SeriesId` | `string(uuid)` | Series Id |
| `SeriesShortName`? | `string` | Series short name |
| `SeriesName`? | `string` | Series name |
| `ReplacementVoucherId`? | `string(uuid)` | Voucher Id of a voucher that replaces this voucher |
| `ReplacesVoucherId`? | `string(uuid)` | Voucher Id of a voucher that this voucher replace |
| `OriginalVoucherId`? | `string(uuid)` | Voucher Id of a voucher that this voucher has been created from |
| `DeletedVoucherId`? | `string(uuid)` | Voucher Id of the voucher that deletes this voucher |
| `OriginalCurrency`? | `string` | Original currency of this voucher |
| `ReferenceId`? | `string` | Reference Id |
| `ReferenceType`? | `string` | Reference Type |
| `Transactions`? | [`Accounting.Transaction`](#schema-accounting-transaction)[] | List of transactions |
| `Attachments` | [`Attachments`](#schema-attachments) |  |

<a id="schema-accounting-voucherimage"></a>
#### `Accounting.VoucherImage`

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | VoucherImage Id |
| `Removed` | `boolean` | True if removed |
| `Data`? | `string(byte)` | Byte data of image |
| `VoucherId` | `string(uuid)` | Voucher Id |
| `ContentType`? | `string` | Content Type of image |

<a id="schema-accounting-voucherimagepost"></a>
#### `Accounting.VoucherImagePost`

| Field | Type | Description |
|---|---|---|
| `Data`? | `string(byte)` | Byte data of image |
| `VoucherId` | `string(uuid)` | Voucher Id |
| `ContentType`? | `string` | Content Type of image |

<a id="schema-accounting-voucherpost"></a>
#### `Accounting.VoucherPost`

| Field | Type | Description |
|---|---|---|
| `Text`? | `string` | Voucher text |
| `ImportSeries`? | `string` | Import serie. Set only if this is an import |
| `ImportNumber`? | `string` | Import number. Set only of this is an import |
| `OriginalCurrency`? | `string` | Original currency |
| `ImportId`? | `string(uuid)` | Import Id. Set only if this is an import |
| `BookingDate` | `string(date-time)` | Booking date |
| `SeriesId` | `string(uuid)` | Series Id |
| `Transactions`? | [`Accounting.TransactionPost`](#schema-accounting-transactionpost)[] | List of transactions |
| `Images`? | [`Accounting.VoucherImagePost`](#schema-accounting-voucherimagepost)[] | List of images |
| `ReferenceId`? | `string` | Reference Id |
| `ReferenceType`? | `string` | Reference Type |
| `ValidateLockedSystemAccounts` | `boolean` | Validate locked system accounts |

<a id="schema-accounting-vouchertype"></a>
#### `Accounting.VoucherType`

Enum: `Unknown`, `IncomingInvoice`, `Receipt`, `Invoice`, `GenericVoucher`
  
_Values_: 0 - Unknown, 1 - IncomingInvoice, 2 - Receipt, 3 - Invoice, 4 - GenericVoucher

<a id="schema-additionalinformationrequired"></a>
#### `AdditionalInformationRequired`

Enum: `None`, `Comment`, `FileOrComment`

<a id="schema-agencyforwardtarget"></a>
#### `AgencyForwardTarget`

Where a byrå forwards a support issue: to Wint or to a byrå colleague.

| Field | Type | Description |
|---|---|---|
| `ToWint` | `boolean` | True sends the issue to the company's Supportansvarig, otherwise its KA, otherwise the general support group. A Supportansvarig or KA who is a member of the byrå is skipped, since owning the case would leave it with the byrå. |
| `PersonId`? | `integer(int32)` | The id of the byrå colleague to forward the issue to. Required (and must be a valid forward target — see `ISupportSystem.GetAgencyForwardTargets`) when Wint.Superkoll.API.Model.AgencyForwardTarget.ToWint is `false`; ignored when it is `true`. |

<a id="schema-agingincominginvoices-agingincominginvoicealreadypaidinfo"></a>
#### `AgingIncomingInvoices.AgingIncomingInvoiceAlreadyPaidInfo`

| Field | Type | Description |
|---|---|---|
| `PaymentDate` | `string(date-time)` |  |
| `Images`? | [`AgingIncomingInvoices.AgingInvoiceImage`](#schema-agingincominginvoices-aginginvoiceimage)[] |  |
| `Message`? | `string` |  |

<a id="schema-agingincominginvoices-agingincominginvoiceapiaction"></a>
#### `AgingIncomingInvoices.AgingIncomingInvoiceApiAction`

Enum: `None`, `OverpaidAwaitingRefund`, `OverpaidInfoSupplied`, `UnderpaidHasBeenPaidInfoSupplied`, `UnderpaidOtherInfoSupplied`, `UnderpaidCreatePayment`, `UnderpaidWithholdPaymentIntentionally`, `InfoSupplied`
  
_Values_: 0 - None, 1 - OverpaidAwaitingRefund, 2 - OverpaidInfoSupplied, 3 - UnderpaidHasBeenPaidInfoSupplied, 4 - UnderpaidOtherInfoSupplied, 5 - UnderpaidCreatePayment, 6 - UnderpaidWithholdPaymentIntentionally, 7 - InfoSupplied

<a id="schema-agingincominginvoices-agingincominginvoicecreatepaymentinfo"></a>
#### `AgingIncomingInvoices.AgingIncomingInvoiceCreatePaymentInfo`

| Field | Type | Description |
|---|---|---|
| `PaymentDate` | `string(date-time)` |  |

<a id="schema-agingincominginvoices-agingincominginvoicecreditedinfo"></a>
#### `AgingIncomingInvoices.AgingIncomingInvoiceCreditedInfo`

| Field | Type | Description |
|---|---|---|
| `Images`? | [`AgingIncomingInvoices.AgingInvoiceImage`](#schema-agingincominginvoices-aginginvoiceimage)[] |  |
| `Message`? | `string` |  |

<a id="schema-agingincominginvoices-agingincominginvoiceoverpaidinfo"></a>
#### `AgingIncomingInvoices.AgingIncomingInvoiceOverpaidInfo`

| Field | Type | Description |
|---|---|---|
| `Images`? | [`AgingIncomingInvoices.AgingInvoiceImage`](#schema-agingincominginvoices-aginginvoiceimage)[] |  |
| `Message`? | `string` |  |

<a id="schema-agingincominginvoices-agingincominginvoiceupdateinfo"></a>
#### `AgingIncomingInvoices.AgingIncomingInvoiceUpdateInfo`

| Field | Type | Description |
|---|---|---|
| `AgingIncomingInvoiceId` | `integer(int32)` |  |
| `Action` | [`AgingIncomingInvoices.AgingIncomingInvoiceApiAction`](#schema-agingincominginvoices-agingincominginvoiceapiaction) |  |
| `CreatePaymentInfo` | [`AgingIncomingInvoices.AgingIncomingInvoiceCreatePaymentInfo`](#schema-agingincominginvoices-agingincominginvoicecreatepaymentinfo) |  |
| `AlreadyPaidInfo` | [`AgingIncomingInvoices.AgingIncomingInvoiceAlreadyPaidInfo`](#schema-agingincominginvoices-agingincominginvoicealreadypaidinfo) |  |
| `CreditedInfo` | [`AgingIncomingInvoices.AgingIncomingInvoiceCreditedInfo`](#schema-agingincominginvoices-agingincominginvoicecreditedinfo) |  |
| `OverpaidInfo` | [`AgingIncomingInvoices.AgingIncomingInvoiceOverpaidInfo`](#schema-agingincominginvoices-agingincominginvoiceoverpaidinfo) |  |
| `Info` | [`AgingIncomingInvoices.AgingInfo`](#schema-agingincominginvoices-aginginfo) |  |

<a id="schema-agingincominginvoices-aginginfo"></a>
#### `AgingIncomingInvoices.AgingInfo`

| Field | Type | Description |
|---|---|---|
| `Images`? | [`AgingIncomingInvoices.AgingInvoiceImage`](#schema-agingincominginvoices-aginginvoiceimage)[] |  |
| `Message`? | `string` |  |

<a id="schema-agingincominginvoices-aginginvoiceimage"></a>
#### `AgingIncomingInvoices.AgingInvoiceImage`

| Field | Type | Description |
|---|---|---|
| `FileName`? | `string` |  |
| `Data`? | `string(byte)` |  |
| `ContentType`? | `string` |  |

<a id="schema-annualaccountsfinancialyear"></a>
#### `AnnualAccountsFinancialYear`

| Field | Type | Description |
|---|---|---|
| `IsAutoAnnualReport` | `boolean` | Indicates whether the processing type of the annual report is automatic or not (manual) |
| `Id` | `integer(int32)` | Id of the financial year |
| `Start` | `string(date-time)` | Start date of the financial year |
| `End` | `string(date-time)` | End date of the financial year |

<a id="schema-article"></a>
#### `Article`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Article Id |
| `IsAgentSaleArticle` | `boolean` | True for system-created agent-sale articles (InvoiceProduct.AgentSaleInvoiceProductType is set). Their revenue account is locked and drives every future commission booking, so the client must hide the account field entirely rather than let the user try and be rejected (decision R2-1). Exposed as a bool rather than the underlying enum so the agent-sale product taxonomy stays an internal concern. |
| `UnitText`? | `string` | Unit text |
| `TotalAmountForLastYearlyPeriod` | `number(double)` | Total amount sold from this article in last 12 months |
| `TotalQuantityForLastYearlyPeriod` | `number(double)` | Total quantity sold from this article in last 12 months |
| `CanRemove` | `boolean` | Whether article can be removed or not |
| `CanToggleActiveState`? | `boolean` | Whether article's active status can be changed |
| `UnitId`? | `integer(int32)` | The id of the unit for this article |
| `Text` | `string` | The name of the article or the text that should be stated on the invoice using this article |
| `UnitPrice` | `number(double)` | The price per unit |
| `Vat` | `number(double)` | VAT that is either 0, 6, 12 or 25 |
| `EuVatProductType` | [`EuVatProductType`](#schema-euvatproducttype) |  |
| `Inactive` | `boolean` | Whether the article is active or not. |
| `Account`? | `integer(int32)` | Revenue account for this article. Omit or send null to leave the current value unchanged; send 0 to clear it; send an account number to set it. A set value must be within the company's allowed revenue accounts for the article's VAT rate (see GET api/Account/RevenueAccounts). Cannot be changed on system-created agent-sale articles. |

<a id="schema-articleimportrequest"></a>
#### `ArticleImportRequest`

| Field | Type | Description |
|---|---|---|
| `CsvUpload` | [`File`](#schema-file) |  |
| `Delimiter` | [`CsvImportDelimiter`](#schema-csvimportdelimiter) |  |
| `ProductTextColumn`? | `string` | Column name for the article name |
| `InvoiceUnitsColumn`? | `string` | Column name for invoice unit of the article |
| `UnitPriceColumn`? | `string` | Column name for unit price of the article |
| `ProductVATColumn`? | `string` | Column name for vat of the article (0, 6, 12 or 25) |
| `EUVATCategoryColumn`? | `string` | Column name for EUVATCategory, (Ej angiven, Okänd, Undantagen, Vara, Tjänst, Trepartshandel) |

<a id="schema-articlepost"></a>
#### `ArticlePost`

| Field | Type | Description |
|---|---|---|
| `UnitId`? | `integer(int32)` | The id of the unit for this article |
| `Text` | `string` | The name of the article or the text that should be stated on the invoice using this article |
| `UnitPrice` | `number(double)` | The price per unit |
| `Vat` | `number(double)` | VAT that is either 0, 6, 12 or 25 |
| `EuVatProductType` | [`EuVatProductType`](#schema-euvatproducttype) |  |
| `Inactive` | `boolean` | Whether the article is active or not. |
| `Account`? | `integer(int32)` | Revenue account for this article. Omit or send null to leave the current value unchanged; send 0 to clear it; send an account number to set it. A set value must be within the company's allowed revenue accounts for the article's VAT rate (see GET api/Account/RevenueAccounts). Cannot be changed on system-created agent-sale articles. |

<a id="schema-articleput"></a>
#### `ArticlePut`

| Field | Type | Description |
|---|---|---|
| `UnitId`? | `integer(int32)` | The id of the unit for this article |
| `Text` | `string` | The name of the article or the text that should be stated on the invoice using this article |
| `UnitPrice` | `number(double)` | The price per unit |
| `Vat` | `number(double)` | VAT that is either 0, 6, 12 or 25 |
| `EuVatProductType` | [`EuVatProductType`](#schema-euvatproducttype) |  |
| `Inactive` | `boolean` | Whether the article is active or not. |
| `Account`? | `integer(int32)` | Revenue account for this article. Omit or send null to leave the current value unchanged; send 0 to clear it; send an account number to set it. A set value must be within the company's allowed revenue accounts for the article's VAT rate (see GET api/Account/RevenueAccounts). Cannot be changed on system-created agent-sale articles. |

<a id="schema-articlesearchresponse"></a>
#### `ArticleSearchResponse`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the article |
| `Name`? | `string` | Name of the article |
| `EUVatCategory` | [`EuVatProductType`](#schema-euvatproducttype) |  |
| `StandardPrice` | `number(double)` | Standard unit price of the article |
| `Vat` | `number(double)` | VAT that is either 0, 6, 12 or 25 |
| `Unit` | [`Unit`](#schema-unit) |  |
| `Account`? | `integer(int32)` | The article's currently configured revenue account, if any. Reflects the same underlying value as Wint.Superkoll.API.Model.ArticlePut.Account, surfaced here for the article-picker/search use case. |
| `IsAgentSaleArticle` | `boolean` | True for system-created agent-sale articles (InvoiceProduct.AgentSaleInvoiceProductType is set). Their revenue account is locked and drives every future commission booking, so the client must hide the account field entirely rather than let the user try and be rejected (decision R2-1). Exposed as a bool rather than the underlying enum so the agent-sale product taxonomy stays an internal concern. |

<a id="schema-attachmentmeta"></a>
#### `AttachmentMeta`

Attachment meta data of an Entity

| Field | Type | Description |
|---|---|---|
| `AttachmentId`? | `string` | The identifier of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |
| `NumberOfPages` | `integer(int32)` | The number of pages the attachment has. |
| `ImageType` | [`ImageType`](#schema-imagetype) |  |

<a id="schema-attachments"></a>
#### `Attachments`

Attachment details of an Entity

| Field | Type | Description |
|---|---|---|
| `NumberOfAttachments` | `integer(int32)` | The number of attachments total on the entity. |
| `AttachmentsMeta`? | [`AttachmentMeta`](#schema-attachmentmeta)[] | The meta data of all the attachments on the entity. |

<a id="schema-authpost"></a>
#### `AuthPost`

| Field | Type | Description |
|---|---|---|
| `Mail`? | `string` |  |
| `Password`? | `string` |  |

<a id="schema-authtokens"></a>
#### `AuthTokens`

| Field | Type | Description |
|---|---|---|
| `AccessToken`? | `string` |  |
| `RefreshToken`? | `string` |  |

<a id="schema-bankbalance"></a>
#### `BankBalance`

The bank balance of a single bank account, as shown in the dashboard bank balance widget.

| Field | Type | Description |
|---|---|---|
| `AccountId` | `integer(int32)` | Id used when changing this account's visibility. See Wint.Superkoll.API.Model.BankBalanceVisibilityPut. |
| `AccountNumber` | `integer(int32)` | The bookkeeping account number the balance is reconciled against, e.g. 1930. |
| `BankName`? | `string` | Name of the bank the balance was read from, when known. |
| `BankAccountNumber`? | `string` | The bank account number the balance came from. |
| `Balance`? | `number(double)` | The balance at Wint.Superkoll.API.Model.BankBalance.BalanceDate. |
| `Currency`? | `string` | The currency the Wint.Superkoll.API.Model.BankBalance.Balance is expressed in, e.g. "SEK". Always render the amount from this rather than assuming kronor — a minority of accounts are held in EUR, USD, GBP, CAD or DKK. |
| `BalanceDate`? | `string(date-time)` | The date the Wint.Superkoll.API.Model.BankBalance.Balance refers to — what the widget prints as "balance as of". |
| `IsStale` | `boolean` | The balance is older than the freshness window, so the widget must mark it rather than present it as the account's current balance. |
| `ImportedAt`? | `string(date-time)` | When the bank statement carrying this balance was imported into Wint. |
| `IsHighlighted` | `boolean` | True for the company's main bank account, which the widget emphasises over the rest. |
| `ShowOnDashboard` | `boolean` | Whether the customer has chosen to show this account in the widget. |

<a id="schema-bankbalancevisibilityput"></a>
#### `BankBalanceVisibilityPut`

A change to whether one account's balance is shown in the dashboard widget.

| Field | Type | Description |
|---|---|---|
| `AccountId` | `integer(int32)` | The Wint.Superkoll.API.Model.BankBalance.AccountId to change. |
| `ShowOnDashboard` | `boolean` | Whether the account's balance should appear in the widget. |

<a id="schema-bookingtreeaccountinfo"></a>
#### `BookingTreeAccountInfo`

| Field | Type | Description |
|---|---|---|
| `AccountId`? | `integer(int32)` | The Id of the account. |
| `AdditionalInformationRequired` | [`AdditionalInformationRequired`](#schema-additionalinformationrequired) |  |

<a id="schema-cashreconciliationattachment"></a>
#### `CashReconciliationAttachment`

Daily cash entry's attachment which will be an image or PDF

| Field | Type | Description |
|---|---|---|
| `ContentType`? | `string` | Attachment content type e.g. application/pdf, image/png, ... |
| `Data`? | `string(byte)` | Attachment data |
| `FileName`? | `string` | The name of the file. |
| `AttachmentId`? | `string` | The identifier of the attachment. |

<a id="schema-cashreconciliationinstance"></a>
#### `CashReconciliationInstance`

Daily cash entry's detailed representation used to Get()

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of daily cash entry |
| `Date` | `string(date-time)` | Booking date of daily cash entry |
| `Items`? | [`CashReconciliationItemInstance`](#schema-cashreconciliationiteminstance)[] | List of account based transaction for the daily cash entry |
| `Attachments`? | [`CashReconciliationAttachment`](#schema-cashreconciliationattachment)[] | Collection of attachments (images, PDFs) for daily cash entries. Used to store multiple attachments. |

<a id="schema-cashreconciliationinstancedescriptor"></a>
#### `CashReconciliationInstanceDescriptor`

Compact details of daily cash entry

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of daily cash entry |
| `Date` | `string(date-time)` | Booking date of daily cash entry |
| `Amount` | `number(double)` | Total sales amount of daily cash entry |
| `OwnerId` | `integer(int32)` | Id of the owner of daily cash entry |
| `OwnerName`? | `string` | Name of the owner of daily cash entry |
| `Difference` | `number(double)` | Difference in sales and payments in SEK |
| `Dimensions`? | `string(uuid)`[] | Dimensions of daily cash entry |
| `AmountSummary`? | `number(double)` | Sum of total sales in SEK (Used only when the filter is configured with IncludeSummary) |
| `DifferenceSummary`? | `number(double)` | Sum of total differences in SEK (Used only when the filter is configured with IncludeSummary) |

<a id="schema-cashreconciliationinstancedto"></a>
#### `CashReconciliationInstanceDto`

Post object to create daily cash entry

| Field | Type | Description |
|---|---|---|
| `Attachment` | [`CashReconciliationAttachment`](#schema-cashreconciliationattachment) |  |
| `Attachments`? | [`CashReconciliationAttachment`](#schema-cashreconciliationattachment)[] | Collection of attachments (images, PDFs) for daily cash entries. Used to store multiple attachments. |
| `Date` | `string(date-time)` | Booking date of daily cash entry |
| `Items`? | [`CashReconciliationItemInstancePost`](#schema-cashreconciliationiteminstancepost)[] | List of account based transaction for daily cash entry |

<a id="schema-cashreconciliationitemcategory"></a>
#### `CashReconciliationItemCategory`

Enum: `Sales`, `PaymentMethod`, `Other`

<a id="schema-cashreconciliationiteminstance"></a>
#### `CashReconciliationItemInstance`

Account based transaction in a daily cash entry

| Field | Type | Description |
|---|---|---|
| `Description`? | `string` | Description in the transaction |
| `AccountType` | [`CashReconciliationItemType`](#schema-cashreconciliationitemtype) |  |
| `Amount` | `number(double)` | Amount of the transaction |
| `CostCenter`? | `string` | Cost center dimension's short name |
| `Project`? | `string` | Project dimension's short name |
| `Category` | [`CashReconciliationItemCategory`](#schema-cashreconciliationitemcategory) |  |

<a id="schema-cashreconciliationiteminstancepost"></a>
#### `CashReconciliationItemInstancePost`

Post object to create account transaction of a daily cash entry

| Field | Type | Description |
|---|---|---|
| `TemplateItemId` | `integer(int32)` | Id of the template item, this should be used when you have duplicated accounts in a single category |
| `Account` | `integer(int32)` | Account number of the transaction |
| `Amount` | `number(double)` | Amount of the transaction |
| `CostCenter`? | `string` | Cost center dimension's short name |
| `Project`? | `string` | Project dimension's short name |
| `Category` | [`CashReconciliationItemCategory`](#schema-cashreconciliationitemcategory) |  |

<a id="schema-cashreconciliationitemtype"></a>
#### `CashReconciliationItemType`

Enum: `Debit`, `Credit`

<a id="schema-cashreconciliationtemplate"></a>
#### `CashReconciliationTemplate`

Company daily cash template

| Field | Type | Description |
|---|---|---|
| `Items`? | [`CashReconciliationTemplateItem`](#schema-cashreconciliationtemplateitem)[] | Company daily cash template items |

<a id="schema-cashreconciliationtemplateitem"></a>
#### `CashReconciliationTemplateItem`

Company daily cash template items

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the template item |
| `Account` | `integer(int32)` | Account number for a template item |
| `Category` | [`CashReconciliationItemCategory`](#schema-cashreconciliationitemcategory) |  |
| `Description`? | `string` | Description for a template item |
| `AccountType` | [`CashReconciliationItemType`](#schema-cashreconciliationitemtype) |  |

<a id="schema-company"></a>
#### `Company`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Company Id |
| `Name`? | `string` | Company name |
| `Org`? | `string` | Company Org-number |
| `Url`? | `string` | Company URL |
| `RelationFlags`? | `integer(int32)` | Company Roles for user *(deprecated)* |
| `ExtendedRelationFlags`? | `integer(int64)` | Company Roles for user |
| `IsPaymentPaused` | `boolean` | Payments are paused - no payments will go out from this company for receipt och invoices |
| `NoVat` | `boolean` | Company is not registered for VAT |
| `ReportsAvailable` | `boolean` | Reports are available |
| `BankBalanceWidgetActivated` | `boolean` | The bank balance dashboard widget is activated for the company (set from Heart). The customer still chooses which accounts it shows. |
| `SalaryDeviationsAvailable` | `boolean` | Individual salary deviations are available for mobile app |
| `CashReconciliationEnabled` | `boolean` | Indicates whether daily cash is available for both the company and the user. |
| `CashReconciliationEnabledForCompany` | `boolean` | Indicates whether daily cash is activated for the company. |
| `RevenueReportingEnabledForCompany` | `boolean` | Indicates whether the company has been onboarded to the new revenue reporting flow. |
| `ReceiptCreator` | `boolean` | Able to submit receipts |
| `ReceiptViewer` | `boolean` | Able to view receipts |
| `SupplierInvoiceCreator` | `boolean` | Able to submit supplier invoices |
| `SupplierInvoiceViewer` | `boolean` | Able to view supplier invoices |
| `SupplierInvoiceAttestor` | `boolean` | Able to attest supplier invoices |
| `GenericDocumentCreator` | `boolean` | Able to submit generic documents |
| `GenericDocumentViewer` | `boolean` | Able to view generic documents |
| `InvoiceCreator` | `boolean` | Able to submit customer invoices |
| `InvoiceUser` | `boolean` | Able to use customer invoices |
| `CommissionSalaryActive` | `boolean` | Indicate whether commission based salary is active for logged in user |
| `CommissionSalaryAvailable` | `boolean` | Indicate whether commission based salary is available for logged in user |
| `LoggedInUserSalaryActive` | `boolean` | Indicate whether salary is active for logged in user |
| `LoggedInUserIsSalaryAdmin` | `boolean` | Indicates whether logged in user is a Salary admin |
| `LoggedInUserIsRevisor` | `boolean` | Indicates whether the logged-in user is an auditor/revisor |
| `LoggedInUserIsAuditorAssistant` | `boolean` | Indicates whether the logged-in user is an auditor assistant (revisorsassistent) linked to an active annual report for this company |
| `LoggedInUserIsMemberOfCompanyAgency` | `boolean` | Indicates whether the logged-in user is a member of the external agency currently chosen for this company (CompanyPersonData.ExternalAgency_Id). Used to decide whether agency-specific UI, such as the support issue user filter, should be shown. |
| `ReceiptDimensionTypes`? | [`DimensionType`](#schema-dimensiontype)[] | Dimension types available for receipts |
| `IncomingInvoiceDimensionTypes`? | [`DimensionType`](#schema-dimensiontype)[] | Dimension types available for incoming invoices |
| `InvoiceDimensionTypes`? | [`DimensionType`](#schema-dimensiontype)[] | Dimension types available for invoices |
| `ReceiptPaymentMethods`? | map<string, [`ReceiptPaymentMethod`](#schema-receiptpaymentmethod)[]> | Payment methods for all persons employeed |
| `ReceiptDimensions`? | [`Dimension`](#schema-dimension)[] | Dimensions available for receipts |
| `InvoiceDimensions`? | [`Dimension`](#schema-dimension)[] | Dimensions available for invoices |
| `FinancialYears`? | [`FinancialYear`](#schema-financialyear)[] | Financial years |
| `IncomingInvoiceDimensions`? | [`Dimension`](#schema-dimension)[] | Dimensions available for incoming invoices |
| `ReceiptCategories`? | [`ReceiptCategory`](#schema-receiptcategory)[] | Categories available for receipts |
| `CashReconciliationDimensionTypes`? | [`DimensionType`](#schema-dimensiontype)[] | Dimension types available for daily cash |
| `CashReconciliationDimensions`? | [`Dimension`](#schema-dimension)[] | Dimensions available for daily cash |
| `CommissionSalaryDimensionType` | [`DimensionType`](#schema-dimensiontype) |  |
| `HasROT` | `boolean` | Has ROT Deductions enabled |
| `HasRUT` | `boolean` | Has RUT Deductions enabled |
| `IndividualSalaryDeviationsAvailable` | `boolean` | Individual salary deviations are available |
| `WintSalaryDeviationsAvailable` | `boolean` | Indicates whether Wint salary deviations are available for the logged-in user |
| `WintSalarySettingsAvailable` | `boolean` | Indicates whether salary settings are edited as Wint salary settings for the logged-in user — also while the company's Wint salary activation is pending, unlike Wint.Superkoll.API.Model.Company.WintSalaryDeviationsAvailable |
| `WintSalaryCommissionAvailable` | `boolean` | Indicates whether the Wint salary commission broker self-view is available for the logged-in user |
| `IncludeCostCenterDimensionToSalary` | `boolean` | Allow cost center tags for the salary. If allowed salary user can have cost center tag |
| `AllowedDeviationTypes`? | [`SalaryDeviationType`](#schema-salarydeviationtype)[] | Allowed salary deviations types for the company |
| `PageroEInvoice` | `boolean` | Pagero e-invoicing enabled |
| `IsRegisteredAtPagero` | `boolean` | If registered at pagero |
| `HideInvoiceDeliveryDate` | `boolean` | If to hide delivery address in invoice creation |
| `DefaultInvoiceNotes`? | `string` | Default notes of invoice |
| `DefaultInvoiceReminderNotes`? | `string` | Default notes of invoice reminders |
| `DefaultInvoicePaymentTerms` | `integer(int32)` | Default payment terms of invoice |
| `DefaultInvoiceLayout` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `DefaultReminderCost`? | `number(double)` | Default reminder fee added to the first reminder of an invoice |
| `DefaultIsAutomaticRemindersEnabled`? | `boolean` | True if automatic reminders are enabled by default for invoices |
| `DefaultAutomaticReminderPeriod`? | `integer(int32)` | Default number of days before next due date after due date of invoice or previous reminder |
| `DefaultAutomaticReminderDelay`? | `integer(int32)` | Default number of days after invoice has been overdue that any automatic reminder is sent |
| `DefaultAutomaticReminderAmountLimit`? | `number(double)` | Default minimum payment amount left needed to send automatic reminders |
| `DefaultAutomaticReminderCountLimit`? | `integer(int32)` | Default maximum number of reminders which will be automatically sent |
| `DefaultAutomaticReminderFeeDeprecationLimit`? | `number(double)` | Default value of which any unpaid reminder fees will be automatically deprecated if under this limit |
| `DefaultInvoiceReminderSendOption` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `DefaultReminderMailSubject`? | `string` | Default mail subject to use for reminder mails |
| `DefaultReminderMailMessage`? | `string` | Default mail message to use for reminder mails |
| `DefaultReminderFileNameTemplate`? | `string` | Reminder file name template |
| `DefaultInvoiceSendOption` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `DefaultInvoiceMailSubject`? | `string` | Default invoice mail subject |
| `DefaultInvoiceMailMessage`? | `string` | Default invoice mail message |
| `DefaultPenaltyInterestSettings` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `IsAssistantsActive` | `boolean` | Can add assistants |
| `SuperkollSalaryType` | [`SuperkollSalaryType`](#schema-superkollsalarytype) |  |
| `CreateSalaryAutoFromSalaryPersonEntry` | `boolean` | Is salary details auto generated |
| `LoggedInUserWintEmail`? | `string` | Wint email of the logged in user |
| `LoggedInUserSelfInvoiceEmail`? | `string` | Self invoice email of the logged in user |
| `InvoiceActivationState` | [`InvoiceActivationState`](#schema-invoiceactivationstate) |  |
| `QuotationActivationState` | [`QuotationActivationState`](#schema-quotationactivationstate) |  |
| `IsTimeReportingEnabled` | `boolean` | Activation of time reporting |
| `LoggedInUserIsBusinessUnitManager` | `boolean` | If current user is a business unit manager for any group |
| `LoggedInUserIsDeviationAdmin` | `boolean` | If current user is a deviation admin |
| `LoggedInUserIsBusinessUnitManagerWithSalaryRights` | `boolean` | If current user is a business unit manager with salary rights for any group |
| `LoggedInUserIsProjectManager` | `boolean` | If current user is a project manager in any project |
| `LoggedInUserIsAllowedToReportTime` | `boolean` | Activation of time reporting |
| `IsDebtCollectionEnabled` | `boolean` | Activation of debt collection If current user is member in any project |
| `LockDate`? | `string(date-time)` | Lock date from the Heart site |
| `ReconciliationDate`? | `string(date-time)` | End date of the most recent reconciled period |
| `IsAgentSalesActive` | `boolean` | If the company has agent sales |
| `HasSavedFinancialStatements` | `boolean` | Indicates whether company has saved financial statements |
| `VisitorAddress` | [`CompanyAdress`](#schema-companyadress) |  |
| `BillingAddress` | [`CompanyAdress`](#schema-companyadress) |  |
| `IsBusinessUnitsEnabled` | `boolean` | Activation of business units |
| `UsedReceiptPaymentMethodTypes`? | [`ReceiptPaymentMethodType`](#schema-receiptpaymentmethodtype)[] | Unique payment methods types used for all receipts |
| `AdditionalInfoNeededInvoiceAccounts`? | [`BookingTreeAccountInfo`](#schema-bookingtreeaccountinfo)[] | The additional information needed invoice accounts. |
| `PaymentAgent` | [`PaymentAgent`](#schema-paymentagent) |  |
| `AllowBookKeepingByCustomer` | `boolean` | Allow to create vouchers from the api |
| `AllowWintCardRegistration` | `boolean` | If the customer has not already registered for a Wint Card and has not accepted\rejected a request for registration |
| `ActiveDeadlineForCompany` | [`Deadlines.Deadline`](#schema-deadlines-deadline) |  |
| `IsSelfInvoicingEnabled` | `boolean` | Activation of self invoices |
| `AnnualAccountsFinancialYear` | [`AnnualAccountsFinancialYear`](#schema-annualaccountsfinancialyear) |  |
| `NoBankIntegration` | `boolean` | True if company does not have an active bank integration |
| `WintSalaryCompanySettings` | [`WintSalary.WintSalaryCompanySettings`](#schema-wintsalary-wintsalarycompanysettings) |  |

<a id="schema-companyadress"></a>
#### `CompanyAdress`

| Field | Type | Description |
|---|---|---|
| `ZipCode`? | `string` | The zip code |
| `Street1`? | `string` | Street 1 |
| `Street2`? | `string` | Street 2 |
| `City`? | `string` | The city |
| `Country`? | `string` | Country code. E.g. SE |

<a id="schema-costforwarding"></a>
#### `CostForwarding`

The forwarding marking on a receipt or supplier invoice.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` |  |
| `State` | [`CostForwardingState`](#schema-costforwardingstate) |  |
| `CustomerId` | `integer(int32)` |  |
| `CustomerName`? | `string` |  |
| `Description`? | `string` |  |
| `MarkupPercentage`? | `number(double)` | The markup entered when the cost was put on the invoice, if any. For reference only. |
| `InvoiceId`? | `integer(int32)` | The customer invoice the cost is reserved on, when State is not ReadyForForwarding. |
| `InvoiceSerialNumber`? | `integer(int32)` |  |

<a id="schema-costforwardingput"></a>
#### `CostForwardingPut`

Marks a receipt or supplier invoice for forwarding to a customer. A null CustomerId removes the marking. No amount is entered; it is derived from the document when invoicing.

| Field | Type | Description |
|---|---|---|
| `CustomerId`? | `integer(int32)` |  |
| `Description`? | `string` | Becomes the invoice row's text. Max 512 characters. |

<a id="schema-costforwardingstate"></a>
#### `CostForwardingState`

Enum: `ReadyForForwarding`, `OnInvoiceDraft`, `Forwarded`
  
_Values_: 0 - ReadyForForwarding, 1 - OnInvoiceDraft, 2 - Forwarded

<a id="schema-creditandreissuechangespost"></a>
#### `CreditAndReissueChangesPost`

| Field | Type | Description |
|---|---|---|
| `NewInvoice` | [`InvoicePut`](#schema-invoiceput) |  |
| `CustomerDetailsChanged` | `boolean` |  |

<a id="schema-creditandreissuepost"></a>
#### `CreditAndReissuePost`

| Field | Type | Description |
|---|---|---|
| `SendCreditInvoice` | `boolean` |  |
| `CreditInvoiceSendOptions` | [`InvoiceSendProperties`](#schema-invoicesendproperties) |  |
| `NewInvoiceSendOptions` | [`InvoiceSendProperties`](#schema-invoicesendproperties) |  |
| `NewInvoice` | [`InvoicePut`](#schema-invoiceput) |  |
| `CustomerDetailsChanged` | `boolean` |  |

<a id="schema-creditandreissueresult"></a>
#### `CreditAndReissueResult`

| Field | Type | Description |
|---|---|---|
| `CreditInvoiceId` | `integer(int32)` |  |
| `NewInvoiceId` | `integer(int32)` |  |
| `ChangedFields`? | [`InvoiceChangedFieldGroup`](#schema-invoicechangedfieldgroup)[] |  |

<a id="schema-csvimportdelimiter"></a>
#### `CsvImportDelimiter`

Enum: `Tab`, `Semicolon`, `Comma`
  
_Values_: 0 - Tab, 1 - Semicolon, 2 - Comma

<a id="schema-currencyvalue"></a>
#### `CurrencyValue`

Represents amount with currency name

| Field | Type | Description |
|---|---|---|
| `Type`? | `string` | Name of the currency |
| `Value` | `number(double)` | Amount |

<a id="schema-customer"></a>
#### `Customer`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The id of the customer which is returned when creating a customer |
| `ReferencePersons`? | `integer(int32)`[] | Reference persons for the customer |
| `IsEUInvoiceCustomer` | `boolean` | If EU Customer |
| `Warnings`? | [`Warning`](#schema-warning)[] | Issues with this customer that needs attention. This is only set when a single customer is fetched using the id. 1 = Customer has at least one EU address but no VAT number, or IncludeVatNumberOnInvoice = false 2 = Customer has invalid VAT number for the delivery address country 3 = Customer has invalid VAT number for the billing address country |
| `Rating`? | `integer(int32)` | Customer Rating |
| `NumOfRecurringInvoices` | `integer(int32)` | Number of active recurring invoices of the customer |
| `NumOfInvoices` | `integer(int32)` | Number of sent invoices of the customer |
| `PurchasedAmount` | `number(double)` | Invoiced amount for the customer |
| `UnpaidAmount` | `number(double)` | Unpaid invoiced amount for the customer |
| `CanRemove`? | `boolean` | Whether the customer can be removed or not. |
| `CanToggleActiveState`? | `boolean` | Whether the customer can be actived or deactivated. |
| `Name` | `string` | The name of the customer |
| `OrgNumber`? | `string` | The organisation number of the customer E.g. 123456-7890 |
| `Type` | [`CustomerType`](#schema-customertype) |  |
| `BillingAddress` | [`CustomerAddress`](#schema-customeraddress) |  |
| `DeliveryAddress` | [`CustomerAddress`](#schema-customeraddress) |  |
| `VatNumber`? | `string` | The vat number of the customer. Optional (e.g. the customer doesn't have a vat number) |
| `GlnNumber`? | `string` | The optional GLN-numer of the customer. |
| `IncludeVatNumberOnInvoice` | `boolean` | Whether the vat number should be included on the invoice or not |
| `PaymentTerms`? | `integer(int32)` | Must be a positive value, if no value is given default value is 0 |
| `EmailAddress`? | `string` | The email address for the customer |
| `AutogiroPayerNumber`? | `string` | If this is a customer that pays using Autogiro and Wint handles it, the payer number has to be supplied |
| `PhoneNumber`? | `string` | Customer phone number |
| `Inactive` | `boolean` | Whether the customer is active or not. |
| `ShowCurrencyCode` | `boolean` | Whether the preferred customer default should be to display the currency code (SEK) instead of the currency (kr). |
| `Language`? | `string` | The language. Either SV or EN |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `ReferencePersonsList`? | [`Reference`](#schema-reference)[] | Reference persons for the customer. On create, list the reference persons to add. On update, send the full list; include Id for existing persons to keep or update, and omit Id (or use 0) for new ones. Omitting an existing reference person from the list, or including them without their Id, removes them; the update may fail with 409 if that person cannot be removed. |
| `PropertyDesignation`? | `string` | Property Designation |
| `TenantsOwnerAssociationOrgNumber`? | `string` | Tenants Owner Association Organization Number |
| `ApartmentNumber`? | `string` | Apartment Number |
| `IsRutEnabled` | `boolean` | Is RUT enabled for this customer |
| `IsRotEnabled` | `boolean` | Is ROT enabled for this customer |
| `PenaltyInterest` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `InvoiceDeliverySettings` | [`InvoiceDeliverySettings`](#schema-invoicedeliverysettings) |  |
| `InvoiceReminderSettings` | [`InvoiceReminderSettings`](#schema-invoiceremindersettings) |  |

<a id="schema-customeraddress"></a>
#### `CustomerAddress`

| Field | Type | Description |
|---|---|---|
| `Street1`? | `string` | Street 1 Max length: 200 characters |
| `Street2`? | `string` | Street 2 Max length: 200 characters |
| `ZipCode`? | `string` | The zip code Max length: 12 characters |
| `City` | `string` | The city Max length: 200 characters |
| `CountryCode`? | `string` | Country code. E.g. SE |

<a id="schema-customerimport"></a>
#### `CustomerImport`

| Field | Type | Description |
|---|---|---|
| `CsvUpload` | [`File`](#schema-file) |  |
| `Delimiter` | [`CsvImportDelimiter`](#schema-csvimportdelimiter) |  |
| `CustomerNameColumn`? | `string` | CSV column for customer name. |
| `OrgNrColumn`? | `string` | CSV column for organization number. |
| `BillingStreetColumn`? | `string` | CSV column for billing street. |
| `BillingStreet2Column`? | `string` | CSV column for secondary billing street. |
| `BillingZipCodeColumn`? | `string` | CSV column for billing zip code. |
| `BillingCityColumn`? | `string` | CSV column for billing city. |
| `BillingCountryCodeColumn`? | `string` | CSV column for billing country code. |
| `DeliveryStreetColumn`? | `string` | CSV column for delivery street code. |
| `DeliveryStreet2Column`? | `string` | CSV column for delivery street code. |
| `DeliveryZipCodeColumn`? | `string` | CSV column for delivery zip code. |
| `DeliveryCityColumn`? | `string` | CSV column for delivery city. |
| `DeliveryCountryCodeColumn`? | `string` | CSV column for delivery country code. |
| `EmailAddressColumn`? | `string` | CSV column for email address. |
| `PhoneNumberColumn`? | `string` | CSV column for phone number. |
| `VatNumberColumn`? | `string` | CSV column for vat number. |
| `GlnNumberColumn`? | `string` | CSV column for GLN-numer of the customer. |
| `IncludeVatNumberOnInvoiceColumn`? | `string` | CSV column for including VAT number on invoices. |
| `CustomerStandardPaymentTermsColumn`? | `string` | CSV column for standard payment terms. |
| `ShowCurrencyCodeColumn`? | `string` | CSV column for showing currency code on invoices. |
| `LanguageColumn`? | `string` | CSV column for language. |
| `ReferencePersonImportColumnMappings`? | [`ReferencePersonImport`](#schema-referencepersonimport)[] | Mappings for reference person import |
| `PropertyDesignationColumn`? | `string` | CSV column for property designation |
| `TenantsOwnerAssociationOrgNumberColumn`? | `string` | CSV column for tenants owner association organization number |
| `ApartmentNumberColumn`? | `string` | CSV column for apartment number |

<a id="schema-customerorgnrsearchresponse"></a>
#### `CustomerOrgNrSearchResponse`

Response when search customers by organization number

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The id of the customer |
| `Name`? | `string` | Name of the customer |
| `OrgNr`? | `string` | Organization number of the customer |

<a id="schema-customerpost"></a>
#### `CustomerPost`

| Field | Type | Description |
|---|---|---|
| `Name` | `string` | The name of the customer |
| `OrgNumber`? | `string` | The organisation number of the customer E.g. 123456-7890 |
| `Type` | [`CustomerType`](#schema-customertype) |  |
| `BillingAddress` | [`CustomerAddress`](#schema-customeraddress) |  |
| `DeliveryAddress` | [`CustomerAddress`](#schema-customeraddress) |  |
| `VatNumber`? | `string` | The vat number of the customer. Optional (e.g. the customer doesn't have a vat number) |
| `GlnNumber`? | `string` | The optional GLN-numer of the customer. |
| `IncludeVatNumberOnInvoice` | `boolean` | Whether the vat number should be included on the invoice or not |
| `PaymentTerms`? | `integer(int32)` | Must be a positive value, if no value is given default value is 0 |
| `EmailAddress`? | `string` | The email address for the customer |
| `AutogiroPayerNumber`? | `string` | If this is a customer that pays using Autogiro and Wint handles it, the payer number has to be supplied |
| `PhoneNumber`? | `string` | Customer phone number |
| `Inactive` | `boolean` | Whether the customer is active or not. |
| `ShowCurrencyCode` | `boolean` | Whether the preferred customer default should be to display the currency code (SEK) instead of the currency (kr). |
| `Language`? | `string` | The language. Either SV or EN |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `ReferencePersonsList`? | [`Reference`](#schema-reference)[] | Reference persons for the customer. On create, list the reference persons to add. On update, send the full list; include Id for existing persons to keep or update, and omit Id (or use 0) for new ones. Omitting an existing reference person from the list, or including them without their Id, removes them; the update may fail with 409 if that person cannot be removed. |
| `PropertyDesignation`? | `string` | Property Designation |
| `TenantsOwnerAssociationOrgNumber`? | `string` | Tenants Owner Association Organization Number |
| `ApartmentNumber`? | `string` | Apartment Number |
| `IsRutEnabled` | `boolean` | Is RUT enabled for this customer |
| `IsRotEnabled` | `boolean` | Is ROT enabled for this customer |
| `PenaltyInterest` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `InvoiceDeliverySettings` | [`InvoiceDeliverySettings`](#schema-invoicedeliverysettings) |  |
| `InvoiceReminderSettings` | [`InvoiceReminderSettings`](#schema-invoiceremindersettings) |  |

<a id="schema-customerput"></a>
#### `CustomerPut`

| Field | Type | Description |
|---|---|---|
| `Name` | `string` | The name of the customer |
| `OrgNumber`? | `string` | The organisation number of the customer E.g. 123456-7890 |
| `Type` | [`CustomerType`](#schema-customertype) |  |
| `BillingAddress` | [`CustomerAddress`](#schema-customeraddress) |  |
| `DeliveryAddress` | [`CustomerAddress`](#schema-customeraddress) |  |
| `VatNumber`? | `string` | The vat number of the customer. Optional (e.g. the customer doesn't have a vat number) |
| `GlnNumber`? | `string` | The optional GLN-numer of the customer. |
| `IncludeVatNumberOnInvoice` | `boolean` | Whether the vat number should be included on the invoice or not |
| `PaymentTerms`? | `integer(int32)` | Must be a positive value, if no value is given default value is 0 |
| `EmailAddress`? | `string` | The email address for the customer |
| `AutogiroPayerNumber`? | `string` | If this is a customer that pays using Autogiro and Wint handles it, the payer number has to be supplied |
| `PhoneNumber`? | `string` | Customer phone number |
| `Inactive` | `boolean` | Whether the customer is active or not. |
| `ShowCurrencyCode` | `boolean` | Whether the preferred customer default should be to display the currency code (SEK) instead of the currency (kr). |
| `Language`? | `string` | The language. Either SV or EN |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `ReferencePersonsList`? | [`Reference`](#schema-reference)[] | Reference persons for the customer. On create, list the reference persons to add. On update, send the full list; include Id for existing persons to keep or update, and omit Id (or use 0) for new ones. Omitting an existing reference person from the list, or including them without their Id, removes them; the update may fail with 409 if that person cannot be removed. |
| `PropertyDesignation`? | `string` | Property Designation |
| `TenantsOwnerAssociationOrgNumber`? | `string` | Tenants Owner Association Organization Number |
| `ApartmentNumber`? | `string` | Apartment Number |
| `IsRutEnabled` | `boolean` | Is RUT enabled for this customer |
| `IsRotEnabled` | `boolean` | Is ROT enabled for this customer |
| `PenaltyInterest` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `InvoiceDeliverySettings` | [`InvoiceDeliverySettings`](#schema-invoicedeliverysettings) |  |
| `InvoiceReminderSettings` | [`InvoiceReminderSettings`](#schema-invoiceremindersettings) |  |

<a id="schema-customerrating"></a>
#### `CustomerRating`

| Field | Type | Description |
|---|---|---|
| `Rating`? | `integer(int32)` | Rating of the customer |

<a id="schema-customersearchresponse"></a>
#### `CustomerSearchResponse`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the customer |
| `Name`? | `string` | Name of the customer |
| `Address`? | `string` | Address of the customer |
| `OrgNr`? | `string` | Organization number of the customer |

<a id="schema-customertype"></a>
#### `CustomerType`

Enum: `Company`, `PrivatePerson`
  
_Values_: 0 - Company, 1 - PrivatePerson

<a id="schema-deadlines-consequencecost"></a>
#### `Deadlines.ConsequenceCost`

Represents a cost associated with a deadline consequence

| Field | Type | Description |
|---|---|---|
| `AmountWithUnit`? | `string` | Amount with the unit for a consequence cost (eg. 100 kr, 5 %) |
| `Description`? | `string` | Description of the consequence cost |

<a id="schema-deadlines-consequencetypes"></a>
#### `Deadlines.ConsequenceTypes`

Enum: `BreachingAccountingLaw`, `ReducedLiquidity`, `VATReportCorrection`, `LateOrWithHeldVATReport`

<a id="schema-deadlines-deadline"></a>
#### `Deadlines.Deadline`

Represents a deadline

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the deadline |
| `Type` | [`Deadlines.DeadlineType`](#schema-deadlines-deadlinetype) |  |
| `State` | [`Deadlines.DeadlineState`](#schema-deadlines-deadlinestate) |  |
| `CanBeUnsubscribed` | `boolean` | Does user has ability to unsubscribe from email reminders |
| `Consequences`? | [`Deadlines.DeadlineConsequence`](#schema-deadlines-deadlineconsequence)[] | Consequence list of the deadline |
| `PeriodEndDate` | `string(date-time)` | Deadline period's end date |

<a id="schema-deadlines-deadlineconsequence"></a>
#### `Deadlines.DeadlineConsequence`

Represents a deadline consequence

| Field | Type | Description |
|---|---|---|
| `Title`? | `string` | Consequence title |
| `Description`? | `string` | Consequence description |
| `AssociatedCosts`? | [`Deadlines.ConsequenceCost`](#schema-deadlines-consequencecost)[] | Costs associated with the consequence |
| `ConsequenceType` | [`Deadlines.ConsequenceTypes`](#schema-deadlines-consequencetypes) |  |

<a id="schema-deadlines-deadlinestate"></a>
#### `Deadlines.DeadlineState`

Enum: `Unknown`, `Active`, `Handled`, `Expired`
  
_Values_: 0 - Unknown, 1 - Active, 2 - Handled, 3 - Expired

<a id="schema-deadlines-deadlinetype"></a>
#### `Deadlines.DeadlineType`

Enum: `Unknown`, `VATPeriodEnd`, `FinancialYearEnd`
  
_Values_: 0 - Unknown, 1 - VATPeriodEnd, 2 - FinancialYearEnd

<a id="schema-declarations-declaration"></a>
#### `Declarations.Declaration`

Api model for declaration data including additional information and external holdings.

| Field | Type | Description |
|---|---|---|
| `PersonId` | `integer(int32)` | Gets or sets the person ID. |
| `Year` | `integer(int32)` | Gets or sets the year. |
| `Comment`? | `string` | Gets or sets the comment from additional information. |
| `SpousePersonalNumber`? | `string` | Gets or sets the spouse's personal number from additional information. |
| `ExternalHoldings`? | [`Declarations.ExternalHolding`](#schema-declarations-externalholding)[] | Gets or sets the list of external holdings. |

<a id="schema-declarations-externalholding"></a>
#### `Declarations.ExternalHolding`

Represents an external holding with company name and ownership percentage.

| Field | Type | Description |
|---|---|---|
| `CompanyName`? | `string` | Gets or sets the company name. |
| `Ownership` | `number(double)` | Gets or sets the ownership percentage. |

<a id="schema-deviationsummary"></a>
#### `DeviationSummary`

Summary of the salary deviation

| Field | Type | Description |
|---|---|---|
| `Unit` | [`UnitOfDeviationValue`](#schema-unitofdeviationvalue) |  |
| `Value` | `number(double)` | Value of deviation summary |

<a id="schema-dimension"></a>
#### `Dimension`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Name of dimension |
| `Id` | `string(uuid)` | Dimension Id |
| `ShortName`? | `string` | Short name of dimension |
| `TypeId` | `string(uuid)` | Dimension Type Id |
| `TypeName`? | `string` | Name of the dimension type |
| `Type` | [`DimensionCompatibilityType`](#schema-dimensioncompatibilitytype) |  |

<a id="schema-dimensioncompatibilitytype"></a>
#### `DimensionCompatibilityType`

Enum: `Default`, `CostCenter`, `Project`, `Tag`, `Supplier`, `Customer`, `Employee`, `User`, `PaymentMethod`, `Seller`, `Article`, `BusinessUnit`, `BusinessUnitManager`, `TimeReportingEmployee`, `Owner`
  
_Values_: 0 - Default, 1 - CostCenter, 2 - Project, 3 - Tag, 4 - Supplier, 5 - Customer, 6 - Employee, 7 - User, 8 - PaymentMethod, 9 - Seller, 10 - Article, 11 - BusinessUnit, 12 - BusinessUnitManager, 13 - TimeReportingEmployee, 14 - Owner

<a id="schema-dimensiondata"></a>
#### `DimensionData`

Common dimension object for both incoming invoices and receipts

| Field | Type | Description |
|---|---|---|
| `DimensionId` | `string(uuid)` | Demension id for the current newDimension object |
| `Amount` | `number(double)` | Amount to be set for dimension specified in DimensionId |

<a id="schema-dimensionpost"></a>
#### `DimensionPost`

| Field | Type | Description |
|---|---|---|
| `DimensionTypeId` | `string(uuid)` | DimensionTypeId |
| `Name`? | `string` | Name of dimension |
| `ShortName`? | `string` | Short name of dimenson |
| `Active` | `boolean` | Dimension is active |

<a id="schema-dimensionput"></a>
#### `DimensionPut`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Name of dimension |
| `ShortName`? | `string` | Short name of dimenson |
| `Active` | `boolean` | Dimension is active |

<a id="schema-dimensiontype"></a>
#### `DimensionType`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` |  |
| `Id` | `string(uuid)` |  |
| `CompatibilityType` | [`DimensionTypes`](#schema-dimensiontypes) |  |
| `Type` | [`DimensionCompatibilityType`](#schema-dimensioncompatibilitytype) |  |
| `IsForced` | `boolean` | If this dimension type is marked as required in dimension settings. If true, when dimensions are submitted, atleast one dimension from this type should be included. |
| `RecommendedDimensionId`? | `string(uuid)` | Recommended dimension for dimension type |

<a id="schema-dimensiontypes"></a>
#### `DimensionTypes`

Enum: `CostCenter`, `Project`
  
_Values_: 0 - CostCenter, 1 - Project

<a id="schema-downpaymentvisibility"></a>
#### `DownPaymentVisibility`

Enum: `DoNotShow`, `ShowOnly`

<a id="schema-editmonthlyreportmarkdownrequest"></a>
#### `EditMonthlyReportMarkdownRequest`

Replaces the report body with a hand-edited version.

| Field | Type | Description |
|---|---|---|
| `Markdown`? | `string` | The full new markdown body. Must not be empty. |

<a id="schema-employee"></a>
#### `Employee`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Name of employee |
| `Mail`? | `string` | Registered e-mail of employee |
| `Pno`? | `string` | Social security number |
| `Id` | `integer(int32)` | Id |
| `SupplierInvoicesAvalible` | `boolean` | True if supplier invoices are available for this employee |

<a id="schema-employeechildassistant"></a>
#### `EmployeeChildAssistant`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the assistant |
| `Name`? | `string` | Name of the assistant |

<a id="schema-employeepost"></a>
#### `EmployeePost`

| Field | Type | Description |
|---|---|---|
| `Mail`? | `string` | E-mail of employee |
| `SalarySettings` | [`EmployeeSalarySetting`](#schema-employeesalarysetting) |  |
| `BusinessUnitId`? | `string(uuid)` | Business unit id which logged in user manages. This will be set only if the logged in user has salary rights permission in a business units. |
| `Name`? | `string` | Name of employee |
| `Pno`? | `string` | Social security number |
| `Phone`? | `string` | Phone number |
| `AdditionalBankAccount`? | `string` | Optional bank account number |
| `AdditionalBankAccountClearing`? | `string` | Optional bank account clearing number |
| `Assistants`? | [`EmployeeChildAssistant`](#schema-employeechildassistant)[] | Persons with right permissions to certify supplier invoices and manage customer invoices |
| `Permissions` | [`Permissions`](#schema-permissions) |  |
| `ProfileImage` | [`ProfileImage`](#schema-profileimage) |  |
| `IncomingInvoiceReferenceNames`? | [`IncomingInvoiceReferenceName`](#schema-incominginvoicereferencename)[] | Incoming invoice reference names |
| `TimeReportingSettings` | [`TimeReportingSettings`](#schema-timereportingsettings) |  |
| `UserTypeId`? | `integer(int32)` | Assigned user type for this employee, or null for none. Must be a type enabled for the company. |

<a id="schema-employeeput"></a>
#### `EmployeePut`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Name of employee |
| `Pno`? | `string` | Social security number |
| `Phone`? | `string` | Phone number |
| `AdditionalBankAccount`? | `string` | Optional bank account number |
| `AdditionalBankAccountClearing`? | `string` | Optional bank account clearing number |
| `Assistants`? | [`EmployeeChildAssistant`](#schema-employeechildassistant)[] | Persons with right permissions to certify supplier invoices and manage customer invoices |
| `Permissions` | [`Permissions`](#schema-permissions) |  |
| `ProfileImage` | [`ProfileImage`](#schema-profileimage) |  |
| `IncomingInvoiceReferenceNames`? | [`IncomingInvoiceReferenceName`](#schema-incominginvoicereferencename)[] | Incoming invoice reference names |
| `TimeReportingSettings` | [`TimeReportingSettings`](#schema-timereportingsettings) |  |
| `UserTypeId`? | `integer(int32)` | Assigned user type for this employee, or null for none. Must be a type enabled for the company. |

<a id="schema-employeesalarysetting"></a>
#### `EmployeeSalarySetting`

| Field | Type | Description |
|---|---|---|
| `CanChangeTerminationReason` | `boolean` | False when a vacation termination settlement already exists in Wint.Salary — the termination reason is then frozen and must not be edited. Defaults to true (changeable). |
| `IsActive` | `boolean` | Is salary active |
| `BankAccount`? | `string` | Bank account |
| `BankAccountClearing`? | `string` | Clearing number for bank account |
| `TaxTable` | [`TaxTableInfo`](#schema-taxtableinfo) |  |
| `EmploymentStartDate`? | `string(date-time)` | Date of employment |
| `EmploymentEndDate`? | `string(date-time)` | End date of the employment |
| `MonthlySalary`? | `number(double)` | Gross monthly salary |
| `EmploymentRate` | `number(double)` | Employment rate |
| `SalaryChangeFrom`? | `string(date-time)` | Apply salary change after this date |
| `EmploymentRateChangeFrom`? | `string(date-time)` | Apply employment rate change after this date |
| `WorkPlaceStreetAddress`? | `string` | Street address where employee is physically working |
| `WorkPlaceCity`? | `string` | City where employee is physically working |
| `Position`? | `string` | Gets or sets the position of the employee |
| `VacationConditions`? | `integer(int32)` | Gets or sets the vacation conditions of the employee |
| `WorkType` | [`EmployeeWorkType`](#schema-employeeworktype) |  |
| `UsualWorkHours`? | `number(double)` | Gets or sets the usual work hours of the employee |
| `Schedule`? | `string` | Gets or sets the schedule of the employee |
| `CostCenter`? | `string(uuid)` | Gets or sets the cost center of the employee's salary |
| `WintSalarySpecificSettings` | [`WintSalary.WintSalarySpecificSettings`](#schema-wintsalary-wintsalaryspecificsettings) |  |
| `TerminationReason` | [`EmploymentTerminationReason`](#schema-employmentterminationreason) |  |

<a id="schema-employeeworktype"></a>
#### `EmployeeWorkType`

Enum: `BlueCollar`, `WhiteCollar`
  
_Values_: 0 - BlueCollar, 1 - WhiteCollar

<a id="schema-employmentterminationreason"></a>
#### `EmploymentTerminationReason`

Enum: `Undefined`, `VoluntaryResignation`, `EmployerNotice`, `MutualAgreement`, `RetirementOrPension`, `Sickness`, `Redundancy`, `Death`, `ChangeOfEmploymentForm`

<a id="schema-entitystatelog"></a>
#### `EntityStateLog`

Entity state log declares status change log for the entity

| Field | Type | Description |
|---|---|---|
| `Status` | `integer(int32)` | The changed status of the entity |
| `Date`? | `string(date-time)` | The timestamp of the change |
| `ChangedById`? | `integer(int32)` | The id of the person who made the change |
| `ChangedByName`? | `string` | The person who made the change |
| `IsIntermediateState` | `boolean` | Whether the state is an intermediate state |
| `Active` | `boolean` | Whether the state is active |

<a id="schema-euvatproducttype"></a>
#### `EuVatProductType`

Enum: `NotDefined`, `Unknown`, `Exempt`, `Goods`, `ThirdPartyTrade`, `Services`

<a id="schema-existingcustomercheckrequest"></a>
#### `ExistingCustomerCheckRequest`

To check for an existing customer with the same details

| Field | Type | Description |
|---|---|---|
| `Id`? | `integer(int32)` | The id of the customer |
| `Name`? | `string` | The name of the customer |
| `BillingAddress` | [`CustomerAddress`](#schema-customeraddress) |  |

<a id="schema-existingcustomercheckresponse"></a>
#### `ExistingCustomerCheckResponse`

To get information of an existing customer with the same details

| Field | Type | Description |
|---|---|---|
| `Id`? | `integer(int32)` | The id of the customer |
| `OrgNumber`? | `string` | The organisation number of the customer E.g. 123456-7890 |

<a id="schema-extendedemployee"></a>
#### `ExtendedEmployee`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id |
| `SupplierInvoicesAvalible` | `boolean` | True if supplier invoices are available for this employee |
| `Mail`? | `string` | E-mail of employee |
| `SalarySettings` | [`EmployeeSalarySetting`](#schema-employeesalarysetting) |  |
| `BusinessUnitId`? | `string(uuid)` | Business unit id which logged in user manages. This will be set only if the logged in user has salary rights permission in a business units. |
| `Name`? | `string` | Name of employee |
| `Pno`? | `string` | Social security number |
| `Phone`? | `string` | Phone number |
| `AdditionalBankAccount`? | `string` | Optional bank account number |
| `AdditionalBankAccountClearing`? | `string` | Optional bank account clearing number |
| `Assistants`? | [`EmployeeChildAssistant`](#schema-employeechildassistant)[] | Persons with right permissions to certify supplier invoices and manage customer invoices |
| `Permissions` | [`Permissions`](#schema-permissions) |  |
| `ProfileImage` | [`ProfileImage`](#schema-profileimage) |  |
| `IncomingInvoiceReferenceNames`? | [`IncomingInvoiceReferenceName`](#schema-incominginvoicereferencename)[] | Incoming invoice reference names |
| `TimeReportingSettings` | [`TimeReportingSettings`](#schema-timereportingsettings) |  |
| `UserTypeId`? | `integer(int32)` | Assigned user type for this employee, or null for none. Must be a type enabled for the company. |

<a id="schema-externalinvoicereference"></a>
#### `ExternalInvoiceReference`

| Field | Type | Description |
|---|---|---|
| `SystemName`? | `string` | Name of external system |
| `ExternalId`? | `string` | Id of the invoice in the external system |

<a id="schema-file"></a>
#### `File`

| Field | Type | Description |
|---|---|---|
| `FileName`? | `string` | Name |
| `ContentType`? | `string` | Content type |
| `Data`? | `string(byte)` | File data |

<a id="schema-financialreport-auditreportfilter"></a>
#### `FinancialReport.AuditReportFilter`

Base filter for audit reports

| Field | Type | Description |
|---|---|---|
| `ReconciliationId`? | `integer(int32)` | MonthlyReconciliation id |
| `EndMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `WidgetDataOnly` | `boolean` | Get top level audit categories only. |
| `IncludeZeroValueRows` | `boolean` | Include categories and accounts with a value of zero. |

<a id="schema-financialreport-auditreportfilterdata"></a>
#### `FinancialReport.AuditReportFilterData`

Holds valid filter values for the Audit balance report

| Field | Type | Description |
|---|---|---|
| `FilterItems`? | [`FinancialReport.AuditReportFilterItem`](#schema-financialreport-auditreportfilteritem)[] |  |

<a id="schema-financialreport-auditreportfilteritem"></a>
#### `FinancialReport.AuditReportFilterItem`

| Field | Type | Description |
|---|---|---|
| `ReconciliationId` | `integer(int32)` |  |
| `StartMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `EndMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |

<a id="schema-financialreport-financialreport"></a>
#### `FinancialReport.FinancialReport`

| Field | Type | Description |
|---|---|---|
| `Rows`? | [`FinancialReport.FinancialReportRow`](#schema-financialreport-financialreportrow)[] |  |
| `Columns`? | `string`[] |  |
| `StartDate`? | `string(date-time)` |  |
| `EndDate`? | `string(date-time)` |  |

<a id="schema-financialreport-financialreportcolumnfilter"></a>
#### `FinancialReport.FinancialReportColumnFilter`

| Field | Type | Description |
|---|---|---|
| `StartMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `EndMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |

<a id="schema-financialreport-financialreportdimensionfilter"></a>
#### `FinancialReport.FinancialReportDimensionFilter`

Base filter for dimension related financial reports

| Field | Type | Description |
|---|---|---|
| `StartMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `EndMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `DimensionType` | `string(uuid)` | Dimension type |
| `OnlyDimensionsWithTransactions`? | `boolean` | Only allow dimensions with transactions |
| `OnlyActiveDimensions`? | `boolean` | Only allow active dimensions |
| `ShowAccountNumber`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `HideAverageMonthAndDifference`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `ExpandAllRows`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |

<a id="schema-financialreport-financialreportfilter"></a>
#### `FinancialReport.FinancialReportFilter`

Base filter for financial reports

| Field | Type | Description |
|---|---|---|
| `Dimensions`? | `string(uuid)`[] | If dimensions are specified, only transactions with the included dimensions will be included in the report |
| `Columns`? | [`FinancialReport.FinancialReportColumnFilter`](#schema-financialreport-financialreportcolumnfilter)[] | The first column specified is the default one. All other columns will include difference compared to the default column. |
| `ShowAccountNumber`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `HideAverageMonthAndDifference`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `ExpandAllRows`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |

<a id="schema-financialreport-financialreportmonthlyfilter"></a>
#### `FinancialReport.FinancialReportMonthlyFilter`

Monthly filter for financial reports

| Field | Type | Description |
|---|---|---|
| `StartMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `EndMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `Dimensions`? | `string(uuid)`[] | If dimensions are specified, only transactions with the included dimensions will be included in the report |
| `ShowAccountNumber`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `HideAverageMonthAndDifference`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `ExpandAllRows`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |

<a id="schema-financialreport-financialreportmultidimensionfilter"></a>
#### `FinancialReport.FinancialReportMultiDimensionFilter`

Filter for multi dimensional financial reports rel

| Field | Type | Description |
|---|---|---|
| `CrossDimensionTypes`? | `string(uuid)`[] | Cross dimension types |
| `StartMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `EndMonth` | [`YearAndMonth`](#schema-yearandmonth) |  |
| `DimensionType` | `string(uuid)` | Dimension type |
| `OnlyDimensionsWithTransactions`? | `boolean` | Only allow dimensions with transactions |
| `OnlyActiveDimensions`? | `boolean` | Only allow active dimensions |
| `ShowAccountNumber`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `HideAverageMonthAndDifference`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |
| `ExpandAllRows`? | `boolean` | Display-only setting stored with saved filters; ignored when building the report |

<a id="schema-financialreport-financialreportrow"></a>
#### `FinancialReport.FinancialReportRow`

| Field | Type | Description |
|---|---|---|
| `Id`? | `string` |  |
| `IsAccount` | `boolean` |  |
| `IsDimension` | `boolean` |  |
| `Type` | [`FinancialReport.FinancialReportRowType`](#schema-financialreport-financialreportrowtype) |  |
| `Description`? | `string` |  |
| `DetailedDescription`? | `string` |  |
| `Columns`? | [`FinancialReport.FinancialReportRowColumn`](#schema-financialreport-financialreportrowcolumn)[] |  |
| `Children`? | [`FinancialReport.FinancialReportRow`](#schema-financialreport-financialreportrow)[] |  |

<a id="schema-financialreport-financialreportrowcolumn"></a>
#### `FinancialReport.FinancialReportRowColumn`

| Field | Type | Description |
|---|---|---|
| `Amount` | `number(double)` |  |
| `Difference` | `number(double)` |  |
| `DifferencePercentage` | `number(double)` |  |
| `IB` | `number(double)` |  |
| `UB` | `number(double)` |  |
| `Checked`? | `boolean` |  |
| `AuditSheetId`? | `integer(int32)` |  |

<a id="schema-financialreport-financialreportrowtype"></a>
#### `FinancialReport.FinancialReportRowType`

Enum: `Category`, `SumSmall`, `Sum`, `Empty`, `Title`, `SumNoFormatting`
  
_Values_: 0 - Category, 1 - SumSmall, 2 - Sum, 3 - Empty, 4 - Title, 5 - SumNoFormatting

<a id="schema-financialyear"></a>
#### `FinancialYear`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the financial year |
| `Start` | `string(date-time)` | Start date of the financial year |
| `End` | `string(date-time)` | End date of the financial year |

<a id="schema-forgotpassword"></a>
#### `ForgotPassword`

| Field | Type | Description |
|---|---|---|
| `Mail`? | `string` |  |

<a id="schema-forwardablecost"></a>
#### `ForwardableCost`

A cost waiting to be forwarded to a customer, with the net amount the invoice row is built from. The client applies markup, VAT rate and any currency conversion.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` |  |
| `SourceDocument`? | `string` | The source document as the user knows it, e.g. "kvitto 7". |
| `ReceiptId`? | `integer(int32)` |  |
| `ReceiptSerialNumber`? | `integer(int32)` |  |
| `IncomingInvoiceId`? | `integer(int32)` |  |
| `SupplierInvoiceNumber`? | `string` | The number the web and app show for the supplier invoice. |
| `SourceDate`? | `string(date-time)` |  |
| `Description`? | `string` |  |
| `NetAmountSek`? | `number(double)` | Net excluding VAT, in SEK. Null until the source document is booked. |
| `IsSelectable` | `boolean` | False while the amount cannot be derived yet ("väntar på bokföring"). |

<a id="schema-generatemonthlyreportrequest"></a>
#### `GenerateMonthlyReportRequest`

Asks for a monthly report for the selected company and a calendar month.

| Field | Type | Description |
|---|---|---|
| `PeriodYear` | `integer(int32)` | Year of the reporting month, e.g. 2026. |
| `PeriodMonth` | `integer(int32)` | Month of the reporting month, 1 to 12. The report always covers the whole calendar month. |
| `Segment`? | `string` | Optional prompt segment. Omit for the default. |
| `Deployment`? | `string` | Optional model override. Omit for the report service's default. |

<a id="schema-imagetype"></a>
#### `ImageType`

Enum: `Receipt`, `IncomingInvoice`, `MissingDocument`, `SalaryDraft`, `Invoice`, `GenericDocument`, `DocumentDraft`, `CashReconciliation`, `Quotation`, `QualifiedShareDividend`, `AnnualReport`, `Voucher`, `IncomeTaxReturn`, `AnnualReportAndIncomeTaxReturn`, `AnnualGeneralMeeting`, `AllAnnualDocuments`, `AnnualReportAndAnnualGeneralMeeting`

<a id="schema-incominginvoiceputinfo"></a>
#### `IncomingInvoicePutInfo`

Incoming Invoice specific data

| Field | Type | Description |
|---|---|---|
| `InvoiceDate`? | `string(date-time)` | Invoice date |
| `AccountNumber` | `integer(int32)` | Bookkeeping account |
| `SupplierId`? | `integer(int32)` | ID of the local supplier if any |
| `Amount`? | `number(double)` | Amount including VAT |
| `VatAmount`? | `number(double)` | VAT amount |
| `DimensionList`? | [`DimensionData`](#schema-dimensiondata)[] | New dimensions structure for the web app TODO: delete if not used in mobile app |
| `Currency`? | `string` | The currency |
| `PeriodisationStart`? | `string(date-time)` | Periodisation start month |
| `PeriodisationEnd`? | `string(date-time)` | Periodisation end month |
| `PeriodisationStartDate`? | `string(date-time)` | Exact dates when the periodisation is date based; null for month based. |
| `PeriodisationEndDate`? | `string(date-time)` |  |

<a id="schema-incominginvoicereferencename"></a>
#### `IncomingInvoiceReferenceName`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id |
| `Name`? | `string` | Reference Name |

<a id="schema-invoice"></a>
#### `Invoice`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The id of the invoice used to GET the invoice. This is not necessary to specify when adding an invoice |
| `WebUrl`? | `string` | Absolute URL to open this invoice in the Wint web app. |
| `Status` | [`InvoiceStatus`](#schema-invoicestatus) |  |
| `SerialNumber`? | `integer(int64)` | Serial number on invoice |
| `Ocr` | `integer(int64)` | Ocr number |
| `OcrText`? | `string` | Ocr number converted to text |
| `RoundValue` | `boolean` | Whether each row should be rounded |
| `Credit` | `boolean` | Whether this invoice is a credit invoice |
| `Payments`? | [`Payment`](#schema-payment)[] | Payments for the invoice |
| `PaymentTerms` | `integer(int32)` | Payment terms for invoice *(read-only)* |
| `LastUpdated` | `string(date-time)` | Last modified timestamp |
| `Warnings`? | [`Warning`](#schema-warning)[] | Issues with this invoice that needs attention. This is only set when a single invoice is fetched using the id of the invoice. 4 = Invoice item with no EuVatProductType category in an invoice for a customer with at least one EU address 5 = Invoice item with a defined EuVatProductType category in an invoice with no VAT number for a customer with at least one EU address 6 = Invoice item with a defined EuVatProductType category in an invoice with invalid VAT number for a customer with at least one EU address |
| `PaymentReminderTitleTemplate`? | `string` | The template for title of payment reminder message |
| `PaymentReminderMessageTemplate`? | `string` | The template for message that will be used in payment reminder email |
| `PaymentReminderTemplate`? | `string` | The template for payment reminder message displayed in invoice |
| `ReminderDueDate`? | `string(date-time)` | New due date after reminder sent |
| `OwnerName`? | `string` | Name of the invoice creator |
| `CanSendLastVersionToPagero` | `boolean` | If last version of invoice can be sent to Pagero |
| `HasNoInvalidEuVatProductTypes` | `boolean` | If no invalid EU Vat product types exist |
| `IsEUCustomer` | `boolean` | If customer is EU Customer |
| `InvoiceWarnings`? | [`Warning`](#schema-warning)[] | Obsolete property which is always set to null. Use Wint.Superkoll.API.Model.Invoice.Warnings instead. *(deprecated)* |
| `InvoicePaymentBgNumber`? | `string` | Bankgiro number of the payment |
| `InvoicePaymentMethod` | [`InvoicePaymentMethod`](#schema-invoicepaymentmethod) |  |
| `PaymentState` | [`InvoicePaymentState`](#schema-invoicepaymentstate) |  |
| `Attachments`? | [`InvoiceAttachment`](#schema-invoiceattachment)[] | List of attachments in the invoice |
| `CustomerName`? | `string` | The name of the customer |
| `CustomerOrgNo`? | `string` | The organization number of the customer |
| `TotalAmount` | `number(double)` | Total amount |
| `TotalReminderCost`? | `number(double)` | The total reminder cost of the invoice |
| `TotalTax` | `number(double)` | Total tax amount |
| `FromRecurring` | `boolean` | Is based on a recurring invoice |
| `RecurringId`? | `integer(int32)` | Parent recurring invoice reference |
| `RecurringInvoiceVersion` | [`RecurringInvoiceVersion`](#schema-recurringinvoiceversion) |  |
| `PaymentDate`? | `string(date-time)` | Payment date. Can be used for notifying Wint of payment fulfillment. Payment fulfillment monitoring is handled by Wint, but this facility can be used when the customer is aware of payment ahead of Wint. |
| `LeftToPay`? | `number(double)` | Remaining amount to be paid |
| `CreditStatus` | [`InvoiceCreditStatus`](#schema-invoicecreditstatus) |  |
| `ReminderInvoicesCount`? | `integer(int32)` | Number of reminder invoices. |
| `Rot`? | `boolean` | whether rot is enable |
| `Rut`? | `boolean` | whether rut is enable |
| `HouseWorkApplicationIsFiled` | `boolean` | whether house work application is filed or not |
| `HasUnbookedHouseWorkCases` | `boolean` |  |
| `FromQuotation` | `boolean` | Is based on a quotation |
| `TotalAmountSummary`? | [`CurrencyValue`](#schema-currencyvalue)[] | Sum of total amount values group by currency (Used only when the filter is configured with IncludeSummary) |
| `RecurringFrequency` | [`RecurringInvoiceFrequency`](#schema-recurringinvoicefrequency) |  |
| `RecurringSendType` | [`RecurringInvoiceSendType`](#schema-recurringinvoicesendtype) |  |
| `RecurringState` | [`RecurringInvoiceState`](#schema-recurringinvoicestate) |  |
| `InvoiceSendInfo` | [`InvoiceSendProperties`](#schema-invoicesendproperties) |  |
| `CreditInvoiceIds`? | `integer(int32)`[] | Credit invoice ids of this invoice |
| `RemainingCostAfterCredit`? | `number(double)` | The remaining cost after the credit invoice/s |
| `PDFCount` | `integer(int32)` | Number of invoice PDFs generated |
| `IsTimeReportingInvoice` | `boolean` | If the invoice has connection to time reports |
| `IsReceiptRepaymentInvoice` | `boolean` | If the invoice has connection to the paid back wint card receipt |
| `OwnerId`? | `integer(int32)` | The invoice owner (defaults to request principal) |
| `CustomerId` | `integer(int32)` | The customer to send the invoice to |
| `CustomerReference` | [`InvoiceReference`](#schema-invoicereference) |  |
| `ContactPerson`? | `string` | Seller reference |
| `Notes`? | `string` | Notes to the invoice |
| `Dimensions`? | `string(uuid)`[] | The dimensions for the invoice |
| `DeliveryDate` | `string(date-time)` | The delivery date |
| `PostingDate` | `string(date-time)` | The posting date |
| `DueDate` | `string(date-time)` | When the due date for the invoice is |
| `ShowReferencePersonInAddress` | `boolean` | Whether the invoice should have the reference name in the address |
| `ShowShippingAddress` | `boolean` | Wheter the invoice should contain the customers' delivery address |
| `ShowCurrencyCode` | `boolean` | Wheter the invoice should show the currency or not. E.g. SEK in the summation row |
| `Language` | `string` | The language of the invoice. Either SV or EN |
| `Currency` | `string` | The currency of the invoice E.g. SEK |
| `CreditedInvoiceId`? | `integer(int32)` | The invoice this credit invoice is referring to. Mandatory if the Credit flag i set to true |
| `ReminderCost`? | `number(double)` | The reminder cost of the invoice |
| `PenaltyInterest` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `ReminderNotes`? | `string` | Notes for the reminder |
| `PaymentOptionId`? | `integer(int32)` | ID of the PaymentOption to use. Default payment option will be used if not specified |
| `Rows` | [`InvoiceRow`](#schema-invoicerow)[] | The rows for the invoice |
| `ExternalInvoiceReferences`? | [`ExternalInvoiceReference`](#schema-externalinvoicereference)[] | List of references to the invoice if it exist in an external system |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `InvoiceHouseWorkType` | [`InvoiceHouseWorkType`](#schema-invoicehouseworktype) |  |
| `InvoiceRotPercentageType` | [`InvoiceRotPercentageType`](#schema-invoicerotpercentagetype) |  |
| `CustomerPersonNumber`? | `string` | Personnumber of the invoice customer |
| `HouseWorkOtherCosts`? | `number(double)` | Other cost related to RUT/ROT |
| `InvoiceRotPropertyType` | [`InvoiceRotPropertyType`](#schema-invoicerotpropertytype) |  |
| `PropertyDesignation`? | `string` | Property for ROT |
| `TenantsOwnerAssociationOrgNumber`? | `string` | Tenant-owners' association's organization number |
| `ApartmentNumber`? | `string` | Apartment number of the customer |
| `QuotationSerialNumber`? | `integer(int32)` | Serial number of the quotation |
| `IsAutomaticRemindersEnabled`? | `boolean` | True if automatic reminders are enabled for the invoice |
| `AutomaticReminderPeriod`? | `integer(int32)` | Number of days after due date of invoice or previous reminder when automatic reminders are sent |
| `AutomaticReminderDelay`? | `integer(int32)` | Number of days after invoice has been overdue that any automatic reminder is sent |
| `AutomaticReminderAmountLimit`? | `number(double)` | Minimum payment amount left needed to send automatic reminders |
| `AutomaticReminderCountLimit`? | `integer(int32)` | The maximum number of reminders which will be automatically sent |
| `AutomaticReminderFeeDeprecationLimit`? | `number(double)` | Any unpaid reminder fees will be automatically deprecated if under this limit |
| `AutomaticReminderNotes`? | `string` | Message to show on invoice on automatic reminders |
| `AutomaticReminderSendMethod` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `AutomaticReminderMailFromType` | [`SendInvoiceMailsFromEnum`](#schema-sendinvoicemailsfromenum) |  |
| `AutomaticReminderMailToType` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `AutomaticReminderMailToAddresses`? | `string` | The mail address to use if ReminderMailToType is set |
| `AutomaticReminderMailSubject`? | `string` | Mail subject to use for reminder mails |
| `AutomaticReminderMailMessage`? | `string` | Mail message to use for reminder mails |
| `InvoiceSource` | [`InvoiceSource`](#schema-invoicesource) |  |
| `OriginOcrNumber`? | `integer(int64)` | This is used for matching payments on invoices that has been created from self invoices. |
| `SelfInvoiceId`? | `string(uuid)` | If the invoice is generated using a self invoice this is the id of the related self invoice |

<a id="schema-invoiceactivationrequest"></a>
#### `InvoiceActivationRequest`

| Field | Type | Description |
|---|---|---|
| `HasSentInvoiceBefore` | `boolean` | If the company has sent invoices before |
| `LastInvoiceNumber`? | `integer(int32)` | The invoice number of the last invoice that was sent if the company has sent invoice before |
| `PreferedStartInvoiceNumber`? | `integer(int32)` | If there's a prefered invoice number to start the invoicing with |
| `HasEUCustomers` | `boolean` | If customers in other EU countries will be invoiced |
| `HasRegisteredForFTax` | `boolean` | If company has registered for F-Tax |

<a id="schema-invoiceactivationstate"></a>
#### `InvoiceActivationState`

Enum: `NotActivated`, `WaitingForActivation`, `Activated`
  
_Values_: 0 - NotActivated, 1 - WaitingForActivation, 2 - Activated

<a id="schema-invoiceattachment"></a>
#### `InvoiceAttachment`

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | The identifier for the attachment. |
| `FileName`? | `string` | The file name of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |
| `Data`? | `string(byte)` | The attachment's data. |

<a id="schema-invoiceattachmentpost"></a>
#### `InvoiceAttachmentPost`

| Field | Type | Description |
|---|---|---|
| `FileName`? | `string` | The file name of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |
| `Data`? | `string(byte)` | The attachment's data. |

<a id="schema-invoicechangedfieldgroup"></a>
#### `InvoiceChangedFieldGroup`

Enum: `Recipient`, `Reference`, `CustomerDetails`, `Rows`, `Amounts`, `Vat`, `RutRot`, `Dates`, `Periodisation`, `Dimensions`, `Appearance`, `Notes`, `Reminders`, `PaymentOption`
  
_Values_: 0 - Recipient, 1 - Reference, 2 - CustomerDetails, 3 - Rows, 4 - Amounts, 5 - Vat, 6 - RutRot, 7 - Dates, 8 - Periodisation, 9 - Dimensions, 10 - Appearance, 11 - Notes, 12 - Reminders, 13 - PaymentOption

<a id="schema-invoicecreditstatus"></a>
#### `InvoiceCreditStatus`

Enum: `Regular`, `Credit`, `Credited`

<a id="schema-invoicedefaultmailoptions"></a>
#### `InvoiceDefaultMailOptions`

Invoice mail form properties.

| Field | Type | Description |
|---|---|---|
| `MailFromList`? | [`InvoiceMailSenderOptions`](#schema-invoicemailsenderoptions)[] | List of senders of the mail. |
| `MailToList`? | [`InvoiceMailRecipientOptions`](#schema-invoicemailrecipientoptions)[] | List of receipients of the mail. |
| `Subject`? | `string` | Subject for the mail. If left empty, the subject which is specified under Superkoll -> Inställningar -> Fakturainställningar -> Fakturamail will be used. |
| `Message`? | `string` | Message for the mail. If left empty, the message specified under Superkoll -> Inställningar -> Fakturainställningar -> Fakturamail will be used. |
| `To` | [`InvoiceMailRecipientOptions`](#schema-invoicemailrecipientoptions) |  |
| `From` | [`InvoiceMailSenderOptions`](#schema-invoicemailsenderoptions) |  |
| `Version`? | `integer(int32)` | Specific version to send |

<a id="schema-invoicedeliverysettings"></a>
#### `InvoiceDeliverySettings`

Represents the default invoice delivery settings.

| Field | Type | Description |
|---|---|---|
| `EnableDeliverySettings` | `boolean` | True if the delivery settings are enabled from customer settings. |
| `DefaultInvoiceSendOption` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `InvoiceTitleTemplate`? | `string` | Invoice title template. This is the default subject of the invoice mail. |
| `InvoiceMessageTemplate`? | `string` | Invoice message template. This is the default message of the invoice mail. |
| `InvoiceFileNameTemplate`? | `string` | Invoice file name template. This is the default filename of the attached invoice of the invoice mail. |
| `InvoiceMailToType` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `CustomInvoiceMailTo`? | `string` | Specifies the mail address to send the invoice to. This is used if Wint.Superkoll.API.Model.InvoiceDeliverySettings.InvoiceMailToType is set to Wint.Superkoll.API.Model.SendInvoiceMailsToEnum.Other. |
| `InvoiceNotes`? | `string` | Notes for the invoice. This is used as a default note in the invoice. |

<a id="schema-invoicedimensionput"></a>
#### `InvoiceDimensionPut`

| Field | Type | Description |
|---|---|---|
| `UseStrictValidation` | `boolean` | Set this if dimensions should be validated in strict mode. If set, required dimensions must be specified. |
| `DimensionList`? | `string(uuid)`[] | The invoice level dimensions for the invoice |

<a id="schema-invoicedue"></a>
#### `InvoiceDue`

| Field | Type | Description |
|---|---|---|
| `DueDate` | `string(date-time)` | The payment due date of the invoice |

<a id="schema-invoicehouseworktype"></a>
#### `InvoiceHouseWorkType`

Enum: `None`, `ROT`, `RUT`

<a id="schema-invoicelistitem"></a>
#### `InvoiceListItem`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The id of the invoice. |
| `WebUrl`? | `string` | Absolute URL to open this invoice in the Wint web app. |
| `SerialNumber` | `integer(int64)` | Serial number on invoice |
| `OwnerId`? | `integer(int32)` | Id of the invoice creator |
| `OwnerName`? | `string` | Name of the invoice creator |
| `FromQuotation` | `boolean` | Is based on a quotation |
| `FromRecurring` | `boolean` | Is based on a recurring invoice |
| `PostingDate` | `string(date-time)` | The posting date |
| `DueDate` | `string(date-time)` | Due date for the invoice |
| `CustomerId` | `integer(int32)` | Id of the invoice customer |
| `CustomerName`? | `string` | The name of the customer |
| `Status` | [`InvoiceStatus`](#schema-invoicestatus) |  |
| `CreditStatus` | [`InvoiceCreditStatus`](#schema-invoicecreditstatus) |  |
| `ReminderInvoicesCount`? | `integer(int32)` | Number of reminder invoices. |
| `Rot`? | `boolean` | whether rot is enable |
| `Rut`? | `boolean` | whether rut is enable |
| `HouseWorkApplicationIsFiled` | `boolean` | whether house work application is filed or not |
| `HasUnbookedHouseWorkCases` | `boolean` |  |
| `Currency`? | `string` | The currency of the invoice E.g. SEK |
| `TotalAmount` | `number(double)` | Total amount |
| `TotalAmountExcludingTax` | `number(double)` | Total amount of the invoice excluding VAT in original currency value. |
| `TotalAmountSummary`? | [`CurrencyValue`](#schema-currencyvalue)[] | Sum of total amount values group by currency (Used only when the filter is configured with IncludeSummary) |
| `LeftToPay`? | `number(double)` | Remaining amount to be paid |
| `LeftToPaySummary`? | [`CurrencyValue`](#schema-currencyvalue)[] | Sum of remaining amount to be paid, group by currency (Used only when the filter is configured with IncludeSummary) |
| `TotalAmountSummarySEK` | [`CurrencyValue`](#schema-currencyvalue) |  |
| `AmountLeftSummarySEK` | [`CurrencyValue`](#schema-currencyvalue) |  |
| `AmountExcludingTaxSummarySEK` | [`CurrencyValue`](#schema-currencyvalue) |  |
| `AmountExcludingTaxSummary`? | [`CurrencyValue`](#schema-currencyvalue)[] | Sum of total amount values (excluding VAT) group by currency (Used only when the filter is configured with IncludeSummary) |
| `BookedAmount`? | `number(double)` | Booked amount in SEK |
| `AmountPaidSEK`? | `number(double)` | Paid amount in SEK |
| `PaymentState` | [`InvoicePaymentState`](#schema-invoicepaymentstate) |  |

<a id="schema-invoicemailoptions"></a>
#### `InvoiceMailOptions`

Options for sending an invoice by mail.

| Field | Type | Description |
|---|---|---|
| `Subject`? | `string` | Subject for the mail. If left empty, the subject which is specified under Superkoll -> Inställningar -> Fakturainställningar -> Fakturamail will be used. |
| `Message`? | `string` | Message for the mail. If left empty, the message specified under Superkoll -> Inställningar -> Fakturainställningar -> Fakturamail will be used. |
| `To` | [`InvoiceMailRecipientOptions`](#schema-invoicemailrecipientoptions) |  |
| `From` | [`InvoiceMailSenderOptions`](#schema-invoicemailsenderoptions) |  |
| `Version`? | `integer(int32)` | Specific version to send |

<a id="schema-invoicemailrecipientoptions"></a>
#### `InvoiceMailRecipientOptions`

Options for the recipient of an invoice mail.

| Field | Type | Description |
|---|---|---|
| `Type` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `Address`? | `string(email)` | The mail address to the recipient. |

<a id="schema-invoicemailsenderoptions"></a>
#### `InvoiceMailSenderOptions`

Options for the sender of an invoice mail.

| Field | Type | Description |
|---|---|---|
| `Type` | [`SendInvoiceMailsFromEnum`](#schema-sendinvoicemailsfromenum) |  |
| `Name`? | `string(email)` | The mail address to the recipient. |
| `Address`? | `string(email)` | The mail address to the recipient. |

<a id="schema-invoiceownerreassignrequest"></a>
#### `InvoiceOwnerReassignRequest`

| Field | Type | Description |
|---|---|---|
| `NewOwnerId` | `integer(int32)` | Id of the new invoice owner |

<a id="schema-invoicepaymentmethod"></a>
#### `InvoicePaymentMethod`

Enum: `Bankgiro`, `Plusgiro`, `Autogiro`

<a id="schema-invoicepaymentoption"></a>
#### `InvoicePaymentOption`

A payment option that can be used on invoices

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The ID of the payment option |
| `Method` | [`InvoicePaymentMethod`](#schema-invoicepaymentmethod) |  |
| `Number`? | `string` | Payment number (e.g. the BG number) |
| `IsDefault` | `boolean` | If this the default payment option (used on invoices where no payment option is specified) |

<a id="schema-invoicepaymentreminder"></a>
#### `InvoicePaymentReminder`

| Field | Type | Description |
|---|---|---|
| `ReminderDueDate` | `string(date-time)` | The date that you want to be reminded of the invoice again |
| `ReminderCost`? | `number(double)` | The fee of the reminder |
| `ReminderMessage`? | `string` | The message of the reminder |

<a id="schema-invoicepaymentstate"></a>
#### `InvoicePaymentState`

Enum: `Unpaid`, `Paid`, `OverdueSoon`, `Overdue`, `PartiallyPaid`, `PartiallyPaidOverdue`

<a id="schema-invoicepdf"></a>
#### `InvoicePdf`

| Field | Type | Description |
|---|---|---|
| `FileName`? | `string` | The file name of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |
| `Data`? | `string(byte)` | The attachment's data. |

<a id="schema-invoicepdftemplate"></a>
#### `InvoicePdfTemplate`

Enum: `Default`, `Classic`
  
_Values_: 0 - Default, 1 - Classic

<a id="schema-invoicepenaltyinteresttype"></a>
#### `InvoicePenaltyInterestType`

Enum: `NoPenaltyInterest`, `Statutory`, `Prearranged`
  
_Values_: 0 - NoPenaltyInterest, 1 - Statutory, 2 - Prearranged

<a id="schema-invoiceperiodisationrowput"></a>
#### `InvoicePeriodisationRowPut`

Desired periodisation for a single invoice item. When Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.Periodisation is true, supply either the month pair (Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationStartYear + Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationStartMonth and the corresponding end values) or the date pair (Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationStartDate + Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationEndDate). When both are supplied the date pair takes precedence (mirrors invoice send-time behaviour).

| Field | Type | Description |
|---|---|---|
| `InvoiceItemId` | `integer(int32)` | Id of the invoice item. |
| `Periodisation` | `boolean` | True to periodise this row, false to remove an existing periodisation. |
| `PeriodisationStartYear`? | `integer(int32)` | Start year of the periodisation period (used together with Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationStartMonth). |
| `PeriodisationStartMonth`? | `integer(int32)` | Start month (1-12) of the periodisation period. |
| `PeriodisationEndYear`? | `integer(int32)` | End year of the periodisation period (used together with Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationEndMonth). |
| `PeriodisationEndMonth`? | `integer(int32)` | End month (1-12) of the periodisation period. |
| `PeriodisationStartDate`? | `string(date-time)` | Optional exact start date for date-based periodisation. When set together with Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationEndDate, the periodisation is day-weighted. |
| `PeriodisationEndDate`? | `string(date-time)` | Optional exact end date for date-based periodisation. See Wint.Superkoll.API.Model.InvoicePeriodisationRowPut.PeriodisationStartDate. |

<a id="schema-invoiceperiodisationsput"></a>
#### `InvoicePeriodisationsPut`

Request body for PUT /api/invoice/{id}/periodisations. Each row addresses one invoice item; rows for items not in this list are not touched.

| Field | Type | Description |
|---|---|---|
| `Rows` | [`InvoicePeriodisationRowPut`](#schema-invoiceperiodisationrowput)[] | Per-invoice-item desired periodisation state. |

<a id="schema-invoicepersonssuggestioncollection"></a>
#### `InvoicePersonsSuggestionCollection`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-searchresult)[] | List of all suggestions |

<a id="schema-invoicepost"></a>
#### `InvoicePost`

| Field | Type | Description |
|---|---|---|
| `Attachments`? | [`InvoiceAttachment`](#schema-invoiceattachment)[] | List of invoice attachments |
| `ForwardedCostIds`? | `integer(int32)`[] | Forwardable costs (see /api/costforwarding/forwardable) to reserve on this invoice. The rows for them are sent in Rows like any other row. Ids already reserved on this invoice are accepted, so a draft may resend them. |
| `CostMarkupPercentage`? | `number(double)` | The markup the client applied to the forwarded rows, recorded for reference. Optional. |
| `AttachForwardedCostDocuments` | `boolean` | Attach the forwarded costs' source documents (receipt images, supplier invoice images) to this invoice. |
| `UseStrictValidation` | `boolean` | Set this if invoices should be validated in strict mode. If set all rules required to be able to send the invoice will be validated. If not set it will be possible to save the invoice in a "draft" mode which could require additional updates before it can be sent. |
| `InvoiceMailInfo` | [`InvoiceSendProperties`](#schema-invoicesendproperties) |  |
| `OwnerId`? | `integer(int32)` | The invoice owner (defaults to request principal) |
| `CustomerId` | `integer(int32)` | The customer to send the invoice to |
| `CustomerReference` | [`InvoiceReference`](#schema-invoicereference) |  |
| `ContactPerson`? | `string` | Seller reference |
| `Notes`? | `string` | Notes to the invoice |
| `Dimensions`? | `string(uuid)`[] | The dimensions for the invoice |
| `DeliveryDate` | `string(date-time)` | The delivery date |
| `PostingDate` | `string(date-time)` | The posting date |
| `DueDate` | `string(date-time)` | When the due date for the invoice is |
| `ShowReferencePersonInAddress` | `boolean` | Whether the invoice should have the reference name in the address |
| `ShowShippingAddress` | `boolean` | Wheter the invoice should contain the customers' delivery address |
| `ShowCurrencyCode` | `boolean` | Wheter the invoice should show the currency or not. E.g. SEK in the summation row |
| `Language` | `string` | The language of the invoice. Either SV or EN |
| `Currency` | `string` | The currency of the invoice E.g. SEK |
| `CreditedInvoiceId`? | `integer(int32)` | The invoice this credit invoice is referring to. Mandatory if the Credit flag i set to true |
| `ReminderCost`? | `number(double)` | The reminder cost of the invoice |
| `PenaltyInterest` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `ReminderNotes`? | `string` | Notes for the reminder |
| `PaymentOptionId`? | `integer(int32)` | ID of the PaymentOption to use. Default payment option will be used if not specified |
| `Rows` | [`InvoiceRow`](#schema-invoicerow)[] | The rows for the invoice |
| `ExternalInvoiceReferences`? | [`ExternalInvoiceReference`](#schema-externalinvoicereference)[] | List of references to the invoice if it exist in an external system |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `InvoiceHouseWorkType` | [`InvoiceHouseWorkType`](#schema-invoicehouseworktype) |  |
| `InvoiceRotPercentageType` | [`InvoiceRotPercentageType`](#schema-invoicerotpercentagetype) |  |
| `CustomerPersonNumber`? | `string` | Personnumber of the invoice customer |
| `HouseWorkOtherCosts`? | `number(double)` | Other cost related to RUT/ROT |
| `InvoiceRotPropertyType` | [`InvoiceRotPropertyType`](#schema-invoicerotpropertytype) |  |
| `PropertyDesignation`? | `string` | Property for ROT |
| `TenantsOwnerAssociationOrgNumber`? | `string` | Tenant-owners' association's organization number |
| `ApartmentNumber`? | `string` | Apartment number of the customer |
| `QuotationSerialNumber`? | `integer(int32)` | Serial number of the quotation |
| `IsAutomaticRemindersEnabled`? | `boolean` | True if automatic reminders are enabled for the invoice |
| `AutomaticReminderPeriod`? | `integer(int32)` | Number of days after due date of invoice or previous reminder when automatic reminders are sent |
| `AutomaticReminderDelay`? | `integer(int32)` | Number of days after invoice has been overdue that any automatic reminder is sent |
| `AutomaticReminderAmountLimit`? | `number(double)` | Minimum payment amount left needed to send automatic reminders |
| `AutomaticReminderCountLimit`? | `integer(int32)` | The maximum number of reminders which will be automatically sent |
| `AutomaticReminderFeeDeprecationLimit`? | `number(double)` | Any unpaid reminder fees will be automatically deprecated if under this limit |
| `AutomaticReminderNotes`? | `string` | Message to show on invoice on automatic reminders |
| `AutomaticReminderSendMethod` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `AutomaticReminderMailFromType` | [`SendInvoiceMailsFromEnum`](#schema-sendinvoicemailsfromenum) |  |
| `AutomaticReminderMailToType` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `AutomaticReminderMailToAddresses`? | `string` | The mail address to use if ReminderMailToType is set |
| `AutomaticReminderMailSubject`? | `string` | Mail subject to use for reminder mails |
| `AutomaticReminderMailMessage`? | `string` | Mail message to use for reminder mails |
| `InvoiceSource` | [`InvoiceSource`](#schema-invoicesource) |  |
| `OriginOcrNumber`? | `integer(int64)` | This is used for matching payments on invoices that has been created from self invoices. |
| `SelfInvoiceId`? | `string(uuid)` | If the invoice is generated using a self invoice this is the id of the related self invoice |

<a id="schema-invoicepreviewrequest"></a>
#### `InvoicePreviewRequest`

| Field | Type | Description |
|---|---|---|
| `SerialNumber`? | `integer(int32)` | Serial number on invoice |
| `OCR`? | `integer(int64)` | OCR number on invoice |
| `OCRText`? | `string` | OCR number on invoice as text |
| `RecurringInvoiceId`? | `integer(int32)` | Related recurring invoice id, if any |
| `RecurringInvoiceVersion` | [`RecurringInvoiceVersion`](#schema-recurringinvoiceversion) |  |
| `Attachments`? | [`InvoiceAttachment`](#schema-invoiceattachment)[] | List of invoice attachments |
| `ForwardedCostIds`? | `integer(int32)`[] | Forwardable costs (see /api/costforwarding/forwardable) to reserve on this invoice. The rows for them are sent in Rows like any other row. Ids already reserved on this invoice are accepted, so a draft may resend them. |
| `CostMarkupPercentage`? | `number(double)` | The markup the client applied to the forwarded rows, recorded for reference. Optional. |
| `AttachForwardedCostDocuments` | `boolean` | Attach the forwarded costs' source documents (receipt images, supplier invoice images) to this invoice. |
| `UseStrictValidation` | `boolean` | Set this if invoices should be validated in strict mode. If set all rules required to be able to send the invoice will be validated. If not set it will be possible to save the invoice in a "draft" mode which could require additional updates before it can be sent. |
| `InvoiceMailInfo` | [`InvoiceSendProperties`](#schema-invoicesendproperties) |  |
| `OwnerId`? | `integer(int32)` | The invoice owner (defaults to request principal) |
| `CustomerId` | `integer(int32)` | The customer to send the invoice to |
| `CustomerReference` | [`InvoiceReference`](#schema-invoicereference) |  |
| `ContactPerson`? | `string` | Seller reference |
| `Notes`? | `string` | Notes to the invoice |
| `Dimensions`? | `string(uuid)`[] | The dimensions for the invoice |
| `DeliveryDate` | `string(date-time)` | The delivery date |
| `PostingDate` | `string(date-time)` | The posting date |
| `DueDate` | `string(date-time)` | When the due date for the invoice is |
| `ShowReferencePersonInAddress` | `boolean` | Whether the invoice should have the reference name in the address |
| `ShowShippingAddress` | `boolean` | Wheter the invoice should contain the customers' delivery address |
| `ShowCurrencyCode` | `boolean` | Wheter the invoice should show the currency or not. E.g. SEK in the summation row |
| `Language` | `string` | The language of the invoice. Either SV or EN |
| `Currency` | `string` | The currency of the invoice E.g. SEK |
| `CreditedInvoiceId`? | `integer(int32)` | The invoice this credit invoice is referring to. Mandatory if the Credit flag i set to true |
| `ReminderCost`? | `number(double)` | The reminder cost of the invoice |
| `PenaltyInterest` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `ReminderNotes`? | `string` | Notes for the reminder |
| `PaymentOptionId`? | `integer(int32)` | ID of the PaymentOption to use. Default payment option will be used if not specified |
| `Rows` | [`InvoiceRow`](#schema-invoicerow)[] | The rows for the invoice |
| `ExternalInvoiceReferences`? | [`ExternalInvoiceReference`](#schema-externalinvoicereference)[] | List of references to the invoice if it exist in an external system |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `InvoiceHouseWorkType` | [`InvoiceHouseWorkType`](#schema-invoicehouseworktype) |  |
| `InvoiceRotPercentageType` | [`InvoiceRotPercentageType`](#schema-invoicerotpercentagetype) |  |
| `CustomerPersonNumber`? | `string` | Personnumber of the invoice customer |
| `HouseWorkOtherCosts`? | `number(double)` | Other cost related to RUT/ROT |
| `InvoiceRotPropertyType` | [`InvoiceRotPropertyType`](#schema-invoicerotpropertytype) |  |
| `PropertyDesignation`? | `string` | Property for ROT |
| `TenantsOwnerAssociationOrgNumber`? | `string` | Tenant-owners' association's organization number |
| `ApartmentNumber`? | `string` | Apartment number of the customer |
| `QuotationSerialNumber`? | `integer(int32)` | Serial number of the quotation |
| `IsAutomaticRemindersEnabled`? | `boolean` | True if automatic reminders are enabled for the invoice |
| `AutomaticReminderPeriod`? | `integer(int32)` | Number of days after due date of invoice or previous reminder when automatic reminders are sent |
| `AutomaticReminderDelay`? | `integer(int32)` | Number of days after invoice has been overdue that any automatic reminder is sent |
| `AutomaticReminderAmountLimit`? | `number(double)` | Minimum payment amount left needed to send automatic reminders |
| `AutomaticReminderCountLimit`? | `integer(int32)` | The maximum number of reminders which will be automatically sent |
| `AutomaticReminderFeeDeprecationLimit`? | `number(double)` | Any unpaid reminder fees will be automatically deprecated if under this limit |
| `AutomaticReminderNotes`? | `string` | Message to show on invoice on automatic reminders |
| `AutomaticReminderSendMethod` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `AutomaticReminderMailFromType` | [`SendInvoiceMailsFromEnum`](#schema-sendinvoicemailsfromenum) |  |
| `AutomaticReminderMailToType` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `AutomaticReminderMailToAddresses`? | `string` | The mail address to use if ReminderMailToType is set |
| `AutomaticReminderMailSubject`? | `string` | Mail subject to use for reminder mails |
| `AutomaticReminderMailMessage`? | `string` | Mail message to use for reminder mails |
| `InvoiceSource` | [`InvoiceSource`](#schema-invoicesource) |  |
| `OriginOcrNumber`? | `integer(int64)` | This is used for matching payments on invoices that has been created from self invoices. |
| `SelfInvoiceId`? | `string(uuid)` | If the invoice is generated using a self invoice this is the id of the related self invoice |

<a id="schema-invoiceput"></a>
#### `InvoicePut`

| Field | Type | Description |
|---|---|---|
| `Attachments`? | [`InvoiceAttachment`](#schema-invoiceattachment)[] | List of invoice attachments |
| `ForwardedCostIds`? | `integer(int32)`[] | Forwardable costs (see /api/costforwarding/forwardable) to reserve on this invoice. The rows for them are sent in Rows like any other row. Ids already reserved on this invoice are accepted, so a draft may resend them. |
| `CostMarkupPercentage`? | `number(double)` | The markup the client applied to the forwarded rows, recorded for reference. Optional. |
| `AttachForwardedCostDocuments` | `boolean` | Attach the forwarded costs' source documents (receipt images, supplier invoice images) to this invoice. |
| `UseStrictValidation` | `boolean` | Set this if invoices should be validated in strict mode. If set all rules required to be able to send the invoice will be validated. If not set it will be possible to save the invoice in a "draft" mode which could require additional updates before it can be sent. |
| `InvoiceMailInfo` | [`InvoiceSendProperties`](#schema-invoicesendproperties) |  |
| `OwnerId`? | `integer(int32)` | The invoice owner (defaults to request principal) |
| `CustomerId` | `integer(int32)` | The customer to send the invoice to |
| `CustomerReference` | [`InvoiceReference`](#schema-invoicereference) |  |
| `ContactPerson`? | `string` | Seller reference |
| `Notes`? | `string` | Notes to the invoice |
| `Dimensions`? | `string(uuid)`[] | The dimensions for the invoice |
| `DeliveryDate` | `string(date-time)` | The delivery date |
| `PostingDate` | `string(date-time)` | The posting date |
| `DueDate` | `string(date-time)` | When the due date for the invoice is |
| `ShowReferencePersonInAddress` | `boolean` | Whether the invoice should have the reference name in the address |
| `ShowShippingAddress` | `boolean` | Wheter the invoice should contain the customers' delivery address |
| `ShowCurrencyCode` | `boolean` | Wheter the invoice should show the currency or not. E.g. SEK in the summation row |
| `Language` | `string` | The language of the invoice. Either SV or EN |
| `Currency` | `string` | The currency of the invoice E.g. SEK |
| `CreditedInvoiceId`? | `integer(int32)` | The invoice this credit invoice is referring to. Mandatory if the Credit flag i set to true |
| `ReminderCost`? | `number(double)` | The reminder cost of the invoice |
| `PenaltyInterest` | [`PenaltyInterestSettings`](#schema-penaltyinterestsettings) |  |
| `ReminderNotes`? | `string` | Notes for the reminder |
| `PaymentOptionId`? | `integer(int32)` | ID of the PaymentOption to use. Default payment option will be used if not specified |
| `Rows` | [`InvoiceRow`](#schema-invoicerow)[] | The rows for the invoice |
| `ExternalInvoiceReferences`? | [`ExternalInvoiceReference`](#schema-externalinvoicereference)[] | List of references to the invoice if it exist in an external system |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `InvoiceHouseWorkType` | [`InvoiceHouseWorkType`](#schema-invoicehouseworktype) |  |
| `InvoiceRotPercentageType` | [`InvoiceRotPercentageType`](#schema-invoicerotpercentagetype) |  |
| `CustomerPersonNumber`? | `string` | Personnumber of the invoice customer |
| `HouseWorkOtherCosts`? | `number(double)` | Other cost related to RUT/ROT |
| `InvoiceRotPropertyType` | [`InvoiceRotPropertyType`](#schema-invoicerotpropertytype) |  |
| `PropertyDesignation`? | `string` | Property for ROT |
| `TenantsOwnerAssociationOrgNumber`? | `string` | Tenant-owners' association's organization number |
| `ApartmentNumber`? | `string` | Apartment number of the customer |
| `QuotationSerialNumber`? | `integer(int32)` | Serial number of the quotation |
| `IsAutomaticRemindersEnabled`? | `boolean` | True if automatic reminders are enabled for the invoice |
| `AutomaticReminderPeriod`? | `integer(int32)` | Number of days after due date of invoice or previous reminder when automatic reminders are sent |
| `AutomaticReminderDelay`? | `integer(int32)` | Number of days after invoice has been overdue that any automatic reminder is sent |
| `AutomaticReminderAmountLimit`? | `number(double)` | Minimum payment amount left needed to send automatic reminders |
| `AutomaticReminderCountLimit`? | `integer(int32)` | The maximum number of reminders which will be automatically sent |
| `AutomaticReminderFeeDeprecationLimit`? | `number(double)` | Any unpaid reminder fees will be automatically deprecated if under this limit |
| `AutomaticReminderNotes`? | `string` | Message to show on invoice on automatic reminders |
| `AutomaticReminderSendMethod` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `AutomaticReminderMailFromType` | [`SendInvoiceMailsFromEnum`](#schema-sendinvoicemailsfromenum) |  |
| `AutomaticReminderMailToType` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `AutomaticReminderMailToAddresses`? | `string` | The mail address to use if ReminderMailToType is set |
| `AutomaticReminderMailSubject`? | `string` | Mail subject to use for reminder mails |
| `AutomaticReminderMailMessage`? | `string` | Mail message to use for reminder mails |
| `InvoiceSource` | [`InvoiceSource`](#schema-invoicesource) |  |
| `OriginOcrNumber`? | `integer(int64)` | This is used for matching payments on invoices that has been created from self invoices. |
| `SelfInvoiceId`? | `string(uuid)` | If the invoice is generated using a self invoice this is the id of the related self invoice |

<a id="schema-invoicereference"></a>
#### `InvoiceReference`

| Field | Type | Description |
|---|---|---|
| `ReferenceId`? | `integer(int32)` | The id to a reference person which is set when creating a customer. Mandatory if reference name is not set, otherwise optional |
| `ReferenceName`? | `string` | A name for the reference. Mandatory if Reference id is not set. Otherwise optional. Will create a reference person |

<a id="schema-invoiceremindersettings"></a>
#### `InvoiceReminderSettings`

Represents the default invoice reminder settings.

| Field | Type | Description |
|---|---|---|
| `EnableReminderSettings` | `boolean` | True if the reminder settings are enabled from customer settings. |
| `ReminderCost`? | `number(double)` | Reminder cost. |
| `IsAutomaticRemindersEnabled`? | `boolean` | True if automatic reminders are enabled. |
| `AutomaticReminderAmountLimit`? | `number(double)` | Automatic reminder amount limit. |
| `AutomaticReminderDelay`? | `integer(int32)` | Automatic reminder delay. |
| `AutomaticReminderPeriod`? | `integer(int32)` | Automatic reminder period. |
| `AutomaticReminderCountLimit`? | `integer(int32)` | Automatic reminder count limit. |
| `InvoiceReminderNotesTemplate`? | `string` | Invoice reminder invoice message template. |
| `InvoiceReminderSendOption` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `InvoiceReminderTitleTemplate`? | `string` | Invoice reminder title template. This is the default subject of the invoice reminder mail. |
| `InvoiceReminderMessageTemplate`? | `string` | Invoice reminder message template. This is the default message of the invoice reminder mail. |
| `InvoiceReminderFilenameTemplate`? | `string` | Invoice reminder filename template. This is the default filename of the attached invoice of the invoice reminder mail. |
| `InvoiceReminderMailToType` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `CustomInvoiceReminderMailTo`? | `string` | Default invoice reminder mail to. This is the default mail to of the invoice reminder mail. |

<a id="schema-invoicerotpercentagetype"></a>
#### `InvoiceRotPercentageType`

Enum: `Standard`, `Temporary2025Increase`

<a id="schema-invoicerotpropertytype"></a>
#### `InvoiceRotPropertyType`

Enum: `None`, `House`, `Condominium`

<a id="schema-invoicerow"></a>
#### `InvoiceRow`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the invoice row |
| `ArticleId` | `integer(int32)` | The id of the article this invoice row is referring to |
| `Quantity` | `number(double)` | The quantity for this row |
| `Description`? | `string` | The description of the row. If article is set, the description will be the article's text |
| `OverriddenDescription`? | `string` | Set this if you want to select an article but modify the article's text |
| `Unit` | [`Unit`](#schema-unit) |  |
| `UnitPrice`? | `number(double)` | The unit price. If article is set, this property will be ignored |
| `OverriddenUnitPrice`? | `number(double)` | Set this if you want to select an article but modify the price |
| `OrderIndex` | `integer(int32)` | Zero-based index |
| `Rot` | `boolean` | If invoice row is ROT. Invoice cannot both contain ROT and RUT invoice rows |
| `Rut` | `boolean` | If invoice row is RUT. Invoice cannot both contain ROT and RUT invoice rows |
| `Vat` | `number(double)` | The VAT percentage. If article is set, this property will be ignored |
| `OverriddenVat`? | `number(double)` | Set this if you want to select an article but modify the VAT percentage |
| `EuVatProductType` | [`EuVatProductType`](#schema-euvatproducttype) |  |
| `Periodisation` | `boolean` | `true` if the invoice row should be booked with a periodisation. If so Wint.Superkoll.API.Model.InvoiceRow.PeriodisationStartYear and Wint.Superkoll.API.Model.InvoiceRow.PeriodisationStartMonth, Wint.Superkoll.API.Model.InvoiceRow.PeriodisationEndYear and Wint.Superkoll.API.Model.InvoiceRow.PeriodisationEndMonth must all be set |
| `PeriodisationStartYear`? | `integer(int32)` | This value should hold the start year of the periodisation if Wint.Superkoll.API.Model.InvoiceRow.Periodisation is `true`. |
| `PeriodisationStartMonth`? | `integer(int32)` | This value should hold the start month of the periodisation if Wint.Superkoll.API.Model.InvoiceRow.Periodisation is `true`. The month should be represented as a number where Jan = 1, Feb = 2 and so forth |
| `PeriodisationEndYear`? | `integer(int32)` | This value should hold the end year of the periodisation if Wint.Superkoll.API.Model.InvoiceRow.Periodisation is `true`. |
| `PeriodisationEndMonth`? | `integer(int32)` | This value should hold the end month of the periodisation if Wint.Superkoll.API.Model.InvoiceRow.Periodisation is `true`. The month should be represented as a number where Jan = 1, Feb = 2 and so forth |
| `PeriodisationStartDate`? | `string(date-time)` | Optional exact start date for date-based (day-weighted) periodisation. When both Wint.Superkoll.API.Model.InvoiceRow.PeriodisationStartDate and Wint.Superkoll.API.Model.InvoiceRow.PeriodisationEndDate are set, the periodisation is split across months proportionally to the number of days in each month that fall within the range. Year/month fields are derived from these dates. |
| `PeriodisationEndDate`? | `string(date-time)` | Optional exact end date for date-based periodisation. See Wint.Superkoll.API.Model.InvoiceRow.PeriodisationStartDate. |
| `Dimensions`? | `string(uuid)`[] | The dimensions for the row |
| `HouseWorkHours`? | `number(double)` | Housework hours for article |
| `MaterialCost`? | `number(double)` | Material cost for article |
| `HouseWorkTypeId`? | `integer(int32)` | Id of housework type |
| `HouseWorkTypeName`? | `string` | Name of housework type |
| `Account`? | `integer(int32)` | The row's locked revenue account, if any. Unlike an article's own revenue account setting (which the client chooses directly), this value is never client-chosen: it is set automatically when the invoice is sent (stamped from the article's revenue account at that moment) or, for a credit note, carried forward from the credited invoice's original row so a later change to the article's account can't retroactively rewrite a historical credit. Submitting a value here has no effect — nothing server-side reads this property back from the request; treat it as read-only and simply display/preserve whatever value a GET response returned. Null until the row has actually been sent or credited. |
| `ArticleAccount`? | `integer(int32)` | The revenue account currently configured on the row's article, or null when the article has none (or the row has no article). Unlike Wint.Superkoll.API.Model.InvoiceRow.Account, which is the value stamped on this row when it was sent, this reflects the article's configuration at the time of the GET and may differ from Wint.Superkoll.API.Model.InvoiceRow.Account on historical invoices. Exposed so a client can mirror the send-time VAT rule (GlobalInvoiceSystemStatic.ValidateItemRevenueAccountVat) when an existing invoice is opened for editing, without a per-row article lookup. Read-only: submitting a value has no effect. |
| `ArticleVat`? | `number(double)` | The VAT rate currently configured on the row's article, or null when the row has no article. This is the rate Wint.Superkoll.API.Model.InvoiceRow.Vat must match for a domestic, non-credit row whose article has a revenue account. Read-only: submitting a value has no effect. |
| `ArticleIsAgentSale`? | `boolean` | True when the row's article is a system-created agent-sale article. Such rows are exempt from the revenue-account VAT rule server-side, so a client mirroring that rule must skip them. Null when the row has no article. Nullable rather than a plain bool so the generated client types don't make a read-only member required on the request side. Read-only: submitting a value has no effect. |

<a id="schema-invoicesendmethod"></a>
#### `InvoiceSendMethod`

Enum: `Email`, `Print`, `MarkAsSent`

<a id="schema-invoicesendproperties"></a>
#### `InvoiceSendProperties`

Specifies invoice send information

| Field | Type | Description |
|---|---|---|
| `InvoiceSendMethod` | [`InvoiceSendMethod`](#schema-invoicesendmethod) |  |
| `MailOptions` | [`InvoiceMailOptions`](#schema-invoicemailoptions) |  |

<a id="schema-invoicesendtype"></a>
#### `InvoiceSendType`

Enum: `SendForPrintOrEInvoice`, `SendByEmail`
  
_Values_: 0 - SendForPrintOrEInvoice, 1 - SendByEmail

<a id="schema-invoicesimilaritem"></a>
#### `InvoiceSimilarItem`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the invoice |
| `Date`? | `string(date-time)` | Invoice date |
| `Receiver`? | `string` | The receiver's name of the invoice |
| `Amount`? | `number(double)` | The total amount of the invoice |
| `Status` | [`InvoiceStatus`](#schema-invoicestatus) |  |
| `Currency`? | `string` | Currency of the invoice |
| `Dimensions`? | `string`[] | Dimensions of the invoice |

<a id="schema-invoicesource"></a>
#### `InvoiceSource`

Enum: `Unknown`, `SelfInvoice`
  
_Values_: 0 - Unknown, 1 - SelfInvoice

<a id="schema-invoicestatus"></a>
#### `InvoiceStatus`

Enum: `NotSent`, `Unpaid`, `OverdueReminderSent`, `OverdueReminderNotSent`, `Paid`, `Cancelled`, `Collection`, `ReminderFeeNotFullyPaid`, `Expires`

<a id="schema-invoiceversioninfo"></a>
#### `InvoiceVersionInfo`

| Field | Type | Description |
|---|---|---|
| `Version` | `integer(int32)` |  |
| `CreatedDate`? | `string(date-time)` |  |
| `DueDate`? | `string(date-time)` |  |
| `Amount` | `number(double)` |  |

<a id="schema-localizedenum"></a>
#### `LocalizedEnum`

Represents an enum value with localized names for multiple languages

| Field | Type | Description |
|---|---|---|
| `NameEn`? | `string` | English name (from LocalizedDisplay attribute) |
| `NameSv`? | `string` | Swedish name (from LocalizedDisplay attribute) |

<a id="schema-loginstate"></a>
#### `LoginState`

Enum: `Success`, `WrongUsernameOrPassword`, `AccountLocked`, `NoCompanies`, `Timeout`, `UnknownBankIdError`, `IncorrectPersonalNumber`, `ForceLoginWithBankId`
  
_Values_: 0 - Success, 1 - WrongUsernameOrPassword, 2 - AccountLocked, 3 - NoCompanies, 4 - Timeout, 5 - UnknownBankIdError, 6 - IncorrectPersonalNumber, 7 - ForceLoginWithBankId

<a id="schema-microsoft-aspnetcore-mvc-problemdetails"></a>
#### `Microsoft.AspNetCore.Mvc.ProblemDetails`

| Field | Type | Description |
|---|---|---|
| `Type`? | `string` |  |
| `Title`? | `string` |  |
| `Status`? | `integer(int32)` |  |
| `Detail`? | `string` |  |
| `Instance`? | `string` |  |

<a id="schema-missingdocumentattachment"></a>
#### `MissingDocumentAttachment`

Full attachment which contains meta data and data.

| Field | Type | Description |
|---|---|---|
| `Data`? | `string(byte)` | The attachment's data. |
| `UploadedFileId`? | `string(uuid)` | The uploaded file to attach. |
| `Id` | `integer(int32)` | The id of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |
| `FileName`? | `string` | The file name of the attachment. |

<a id="schema-missingdocumentimage"></a>
#### `MissingDocumentImage`

| Field | Type | Description |
|---|---|---|
| `Data`? | `string(byte)` |  |
| `ContentType`? | `string` |  |

<a id="schema-missingdocumentput"></a>
#### `MissingDocumentPut`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` |  |
| `Explanation`? | `string` | The explanation of the missing document. |
| `Images`? | [`MissingDocumentImage`](#schema-missingdocumentimage)[] |  *(deprecated)* |
| `Attachments`? | [`MissingDocumentAttachment`](#schema-missingdocumentattachment)[] | Attachments that should be added to the missing document. |
| `BookWithoutImage` | `boolean` | Whether the missing document should be booked without an image. This is in case the image can't be retrieved at the moment. |
| `MissingDocumentType` | [`MissingDocumentPutType`](#schema-missingdocumentputtype) |  |
| `IncomingInvoiceInfo` | [`IncomingInvoicePutInfo`](#schema-incominginvoiceputinfo) |  |
| `ReceiptInfo` | [`ReceiptPutInfo`](#schema-receiptputinfo) |  |
| `DimensionList`? | [`DimensionData`](#schema-dimensiondata)[] | Dimensions for the missing document |

<a id="schema-missingdocumentputtype"></a>
#### `MissingDocumentPutType`

Enum: `Receipt`, `IncomingInvoice`, `Other`
  
_Values_: 1 - Receipt, 2 - IncomingInvoice, 3 - Other

<a id="schema-monthlyreport"></a>
#### `MonthlyReport`

A monthly report with its current body and history, for the accountant's review view.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier of the report. |
| `PeriodStart` | `string(date-time)` | First day of the reporting period. |
| `PeriodEnd` | `string(date-time)` | Last day of the reporting period. |
| `Segment`? | `string` | Prompt segment the report was generated with. |
| `Status` | [`MonthlyReportStatus`](#schema-monthlyreportstatus) |  |
| `CurrentIteration` | `integer(int32)` | Number of the current iteration; bumps on every regeneration or edit. |
| `CurrentMarkdown`? | `string` | Markdown of the current iteration. Empty while Wint.Superkoll.API.Model.MonthlyReportStatus.Generating. |
| `CurrentRenderedHtml`? | `string` | Server-rendered HTML of the current iteration, sanitized by the report service. Render as-is. |
| `ApprovedAt`? | `string(date-time)` | When the report was approved for the customer; null until then. |
| `ApprovedByUserId`? | `integer(int32)` | Person who approved the report; null until then. |
| `UpdatedAt`? | `string(date-time)` | When the report's content last changed: generated, regenerated or edited. Approval and revocation leave it alone; Wint.Superkoll.API.Model.MonthlyReport.ApprovedAt covers those. Null on reports written before the service tracked it. |
| `Iterations`? | [`MonthlyReportIteration`](#schema-monthlyreportiteration)[] | Every pass so far, oldest first. |

<a id="schema-monthlyreportcompanyinstruction"></a>
#### `MonthlyReportCompanyInstruction`

The advisor's standing instruction for the selected company's monthly reports. The report service sends it to the model on every generation and regeneration.

| Field | Type | Description |
|---|---|---|
| `Text`? | `string` | The instruction, at most 4000 characters. Null when the company has none; saving empty text removes it. |

<a id="schema-monthlyreportiteration"></a>
#### `MonthlyReportIteration`

One generation or edit pass of a monthly report, kept as an audit trail.

| Field | Type | Description |
|---|---|---|
| `IterationNumber` | `integer(int32)` | 1-based sequence number of the pass. |
| `Markdown`? | `string` | The markdown this pass produced. |
| `KaFeedback`? | `string` | The reviewer feedback that drove this pass, if any. A manual edit carries a marker instead. |

<a id="schema-monthlyreportstatus"></a>
#### `MonthlyReportStatus`

Enum: `Generating`, `Draft`, `Failed`, `ApprovedForCustomer`, `Published`, `Unknown`

<a id="schema-monthlyreportsummary"></a>
#### `MonthlyReportSummary`

Identity and state of a monthly report without its body: the rows of the list, and what a create returns, since the body does not exist yet then.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier of the report. Poll `GET api/MonthlyReports/{id}` with it. |
| `PeriodStart` | `string(date-time)` | First day of the reporting period. |
| `PeriodEnd` | `string(date-time)` | Last day of the reporting period. |
| `Status` | [`MonthlyReportStatus`](#schema-monthlyreportstatus) |  |
| `ApprovedAt`? | `string(date-time)` | When the report was approved for the customer; null until then. |
| `UpdatedAt`? | `string(date-time)` | When the report's content last changed; approval and revocation leave it alone. Null on reports written before the service tracked it, so a list shows no date rather than an invented one. |

<a id="schema-payment"></a>
#### `Payment`

| Field | Type | Description |
|---|---|---|
| `Amount` | `number(double)` |  |
| `BookedAmount` | `number(double)` |  |
| `Date` | `string(date-time)` |  |

<a id="schema-paymentagent"></a>
#### `PaymentAgent`

Enum: `LegacyBGC`, `SEB`, `Handelsbanken`, `Nordea`, `PaymentService`, `Swedbank`, `BankService`

<a id="schema-paymentstate"></a>
#### `PaymentState`

Enum: `Unpaid`, `Paid`

<a id="schema-penaltyinterestsettings"></a>
#### `PenaltyInterestSettings`

| Field | Type | Description |
|---|---|---|
| `Type` | [`InvoicePenaltyInterestType`](#schema-invoicepenaltyinteresttype) |  |
| `Rate`? | `number(double)` | The reminder penalty interest rate |

<a id="schema-permissions"></a>
#### `Permissions`

| Field | Type | Description |
|---|---|---|
| `CEO` | `boolean` |  |
| `Contact` | `boolean` |  |
| `Employee` | `boolean` |  |
| `Documents` | `boolean` |  |
| `UploadGenericDocuments` | `boolean` |  |
| `IncomingInvoicesOverview` | `boolean` |  |
| `IncomingInvoices` | `boolean` |  |
| `InvoicesAdmin` | `boolean` |  |
| `Invoices` | `boolean` |  |
| `ReceiptsAdmin` | `boolean` |  |
| `Receipts` | `boolean` |  |
| `Admin` | `boolean` |  |
| `Reports` | `boolean` |  |
| `IncomingInvoicesAdmin` | `boolean` |  |
| `IncomingInvoicesSignee` | `boolean` |  |
| `Agreement` | `boolean` |  |
| `CashReconciliation` | `boolean` |  |
| `PaymentFileSignee` | `boolean` |  |
| `MissingDocumentAdmin` | `boolean` |  |
| `Auditor` | `boolean` |  |
| `Revisor` | `boolean` |  |
| `SalaryAdmin` | `boolean` |  |
| `PaymentSignee` | `boolean` |  |
| `StoppedPaymentAdmin` | `boolean` |  |
| `Advisor`? | `boolean` |  |
| `DeviationAdmin` | `boolean` |  |
| `Board` | `boolean` |  |

<a id="schema-personmonthlysalarydeviation"></a>
#### `PersonMonthlySalaryDeviation`

Person salary deviation for a month

| Field | Type | Description |
|---|---|---|
| `PersonId` | `integer(int32)` | Id of person the record belongs to |
| `PersonName`? | `string` | Name of person the record belongs to |
| `YearAndMonth` | `integer(int32)` | Year and month e.g. YYYYMM |
| `State` | [`SalaryDeviationMonthState`](#schema-salarydeviationmonthstate) |  |
| `Total` | `number(double)` | Total deviation salary |

<a id="schema-profileimage"></a>
#### `ProfileImage`

| Field | Type | Description |
|---|---|---|
| `ImageData`? | `string(byte)` |  |
| `ContentType`? | `string` |  |

<a id="schema-profileroutineput"></a>
#### `ProfileRoutinePut`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the profile routine |
| `State` | [`ProfileRoutineState`](#schema-profileroutinestate) |  |

<a id="schema-profileroutinestate"></a>
#### `ProfileRoutineState`

Enum: `Pending`, `Started`, `Done`

<a id="schema-questionsandanswers-answerkind"></a>
#### `QuestionsAndAnswers.AnswerKind`

Enum: `Numeric`, `Boolean`, `Text`, `Matrix`, `Selection`, `File`, `StringSelection`, `SingleLineText`

<a id="schema-questionsandanswers-fileanswerfilemodel"></a>
#### `QuestionsAndAnswers.FileAnswerFileModel`

Describes a file answer.

| Field | Type | Description |
|---|---|---|
| `FileName`? | `string` | Gets the name of the file. |
| `MediaType`? | `string` | Gets the media type (formely MIME-type) of the Wint.Superkoll.API.Model.QuestionsAndAnswers.FileAnswerFileModel.FileContent. |
| `FileContent`? | `string` | Gets the base-64 encoded file contents. |
| `FileId` | `string(uuid)` | Gets the `Id` of the file data. |

<a id="schema-questionsandanswers-linkmodel"></a>
#### `QuestionsAndAnswers.LinkModel`

Describes a link.

| Field | Type | Description |
|---|---|---|
| `Href`? | `string` | Gets or sets the href of the link. |
| `Ordinal` | `integer(int32)` | Gets the ordinal. |
| `Title`? | `string` | Gets or sets the title. |
| `Value`? | `string` | Gets or sets the content contained in the link. |

<a id="schema-questionsandanswers-matrixvaluemodel"></a>
#### `QuestionsAndAnswers.MatrixValueModel`

Describes a matrix value specified in input.

| Field | Type | Description |
|---|---|---|
| `TextValue`? | `string` | Gets the text value. |
| `BooleanValue`? | `boolean` | Gets the boolean value. |
| `NumericValue`? | `integer(int32)` | Gets the numeric value. |
| `RowOrdinal` | `integer(int32)` | Gets the row ordinal. |
| `ColumnOrdinal` | `integer(int32)` | Gets the column ordinal. |

<a id="schema-questionsandanswers-questionfiledefinitionmodel"></a>
#### `QuestionsAndAnswers.QuestionFileDefinitionModel`

Describes the definition of a question whose answer would be made using file upload(s).

| Field | Type | Description |
|---|---|---|
| `MinimumFileCount` | `integer(int32)` | Gets the required number of files. |
| `MaximumFileCount`? | `integer(int32)` | Gets the maximum number of files allowed. |
| `MediaTypes`? | `string`[] | Gets the sequence of allowed media types. |

<a id="schema-questionsandanswers-questionmatrixcolumndefinitionmodel"></a>
#### `QuestionsAndAnswers.QuestionMatrixColumnDefinitionModel`

Describes a column definition of a matrix question.

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Gets or sets the name of the column. |
| `Ordinal` | `integer(int32)` | Gets the ordinal of the column. |
| `ValueKind` | [`QuestionsAndAnswers.QuestionMatrixValueKind`](#schema-questionsandanswers-questionmatrixvaluekind) |  |

<a id="schema-questionsandanswers-questionmatrixdefinitionmodel"></a>
#### `QuestionsAndAnswers.QuestionMatrixDefinitionModel`

Describe a question matrix definition.

| Field | Type | Description |
|---|---|---|
| `QuestionMatrixColumnDefinitions`? | [`QuestionsAndAnswers.QuestionMatrixColumnDefinitionModel`](#schema-questionsandanswers-questionmatrixcolumndefinitionmodel)[] | Gets the sequence of columns in the matrix. |
| `RowCount`? | `integer(int32)` | Gets the required number of rows in the matrix. |

<a id="schema-questionsandanswers-questionmatrixvaluekind"></a>
#### `QuestionsAndAnswers.QuestionMatrixValueKind`

Enum: `Numeric`, `Boolean`, `Text`

<a id="schema-questionsandanswers-questionselectiondefinitionmodel"></a>
#### `QuestionsAndAnswers.QuestionSelectionDefinitionModel`

| Field | Type | Description |
|---|---|---|
| `MultiSelection` | `boolean` | Gets a value indicating if multi selection is accepted. |
| `SelectionValues`? | [`QuestionsAndAnswers.SelectionValueModel`](#schema-questionsandanswers-selectionvaluemodel)[] | Gets the sequence of available selection values. |

<a id="schema-questionsandanswers-questionstringselectiondefinitionmodel"></a>
#### `QuestionsAndAnswers.QuestionStringSelectionDefinitionModel`

| Field | Type | Description |
|---|---|---|
| `MultiSelection` | `boolean` | Gets a value indicating if multi selection is accepted. |
| `SelectionValues`? | [`QuestionsAndAnswers.StringSelectionValueModel`](#schema-questionsandanswers-stringselectionvaluemodel)[] | Gets the sequence of available selection values. |

<a id="schema-questionsandanswers-selectionvaluemodel"></a>
#### `QuestionsAndAnswers.SelectionValueModel`

| Field | Type | Description |
|---|---|---|
| `Description`? | `string` | Gets or sets the description of this selection. |
| `Ordinal` | `integer(int32)` | Gets or sets the ordinal. |
| `Value` | `integer(int32)` | Gets or sets the value of this selection. |

<a id="schema-questionsandanswers-stringselectionvaluemodel"></a>
#### `QuestionsAndAnswers.StringSelectionValueModel`

| Field | Type | Description |
|---|---|---|
| `Description`? | `string` | Gets or sets the description of this selection. |
| `Ordinal` | `integer(int32)` | Gets or sets the ordinal. |
| `Value`? | `string` | Gets or sets the value of this selection. |

<a id="schema-quotationactivationstate"></a>
#### `QuotationActivationState`

Enum: `NotActivated`, `Activated`

<a id="schema-receipt"></a>
#### `Receipt`

A representation of a receipt.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier of the receipt. |
| `State` | [`ReceiptStateApiModel`](#schema-receiptstateapimodel) |  |
| `HasImages` | `boolean` | Whether the receipt has images or not. |
| `Meta` | [`ReceiptMeta`](#schema-receiptmeta) |  |
| `CreatedByPersonName`? | `string` | Name of the person who created this receipt |
| `CreatedByPersonId`? | `integer(int32)` | Id of the person who created this receipt |
| `PaymentMethodName`? | `string` | Name of the payment method used to pay for this receipt |
| `CategoryName`? | `string` | Name of the category for this receipt |
| `LastUpdated` | `string(date-time)` | Last modified timestamp |
| `SendBackData` | [`ReceiptSendBackData`](#schema-receiptsendbackdata) |  |
| `Personnumber`? | `string` | Personnumber of the person who created this receipt |
| `PaymentState` | [`PaymentState`](#schema-paymentstate) |  |
| `RecipientClearingNumber`? | `string` | Bank clearing number of the person who created this receipt |
| `RecipientAccount`? | `string` | Bank account number of the person who created this receipt |
| `PaymentDate`? | `string(date-time)` | payment date of the receipt |
| `PaidOut` | `boolean` | Whether receipt is paid out or not |
| `PaymentMethods`? | [`ReceiptPaymentMethod`](#schema-receiptpaymentmethod)[] | Available receipt payment methods for the receipt *(deprecated)* |
| `TotalAmountSummary`? | [`CurrencyValue`](#schema-currencyvalue)[] | Sum of total amount values group by currency (Used only when the filter is configured with IncludeSummary) |
| `TotalAmountSummarySEK` | `number(double)` | Sum of total amount values in kr (Used only when the filter is configured with IncludeSummary) |
| `SerialNumber` | `integer(int32)` | Serial number of receipt |
| `CanPayEmployee` | `boolean` | Do we have the neccessary information to pay out this receipt to the employee? |
| `HasMissingPaymentDetails` | `boolean` | Person doesn't have a swedish personnumber and or missing bankaccount |
| `DocumentDraftId`? | `integer(int32)` | Connected document draft id |
| `IsMatchedToDocumentDraftViaAutomationService` | `boolean` | Indicates whether the receipt is matched to a document draft via automation service |
| `DateTime` | `string(date-time)` | When the receipt was created |
| `Dimensions`? | `string(uuid)`[] | Dimensions of the receipt |
| `DimensionList`? | [`DimensionData`](#schema-dimensiondata)[] | New dimensions structure for the web app |
| `Comment`? | `string` | User comment on receipt |
| `ReceiptCategoryId`? | `integer(int32)` | Id of receipt category |
| `PaymentMethodId`? | `integer(int32)` | Id of receipt payment method |
| `Intent`? | `string` |  |
| `Amount` | `number(double)` | Ammount paid |
| `PaymentMethodType` | [`ReceiptPaymentMethodType`](#schema-receiptpaymentmethodtype) |  |
| `Persons`? | [`ReceiptPerson`](#schema-receiptperson)[] | People the receipt concerns |
| `Images`? | `string(byte)`[] |  *(deprecated)* |
| `ClientId`? | `string(uuid)` |  |
| `Currency`? | `string` | Currency of the receipt |
| `Attachments`? | [`ReceiptAttachment`](#schema-receiptattachment)[] | The attachments of the receipt. |
| `SupplierName`? | `string` | Name of the supplier. |
| `IsOtherPaymentMethod` | `boolean` | The flag indicating if the payment method is "Other" from a classified receipt that comes originally from a GenericVoucher submission. But the DocumentClassificationService has identified this document as a receipt. Please look at this user story for more information: https://app.clickup.com/t/4523827/DEV-20076 |
| `OtherPaymentMethodExplanation`? | `string` | Explanation from the user for the selection of the "Other" payment method. Will always contain a value if "IsOtherPaymentMethod" is true. |

<a id="schema-receiptattachment"></a>
#### `ReceiptAttachment`

Full attachment which contains meta data and data of the attachment.

| Field | Type | Description |
|---|---|---|
| `Data`? | `string(byte)` | The attachment's data. |
| `Id` | `integer(int32)` | The identifier of the attachment. |
| `FileName`? | `string` | The file name of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |

<a id="schema-receiptcategory"></a>
#### `ReceiptCategory`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` |  |
| `Name`? | `string` |  |
| `Type`? | `integer(int32)` |  *(deprecated)* |
| `CategoryType` | [`ReceiptCategoryType`](#schema-receiptcategorytype) |  |

<a id="schema-receiptcategorytype"></a>
#### `ReceiptCategoryType`

Enum: `Representation`, `Fuel`, `ComputersAndAccessories`, `OfficeSupplies`, `OfficeCoffee`, `Other`, `TravelExpenses`, `Postage`, `PurchasesOfGoods`, `ITServiceOrSoftware`, `EmployeeRepresentation`
  
_Values_: 0 - Representation, 1 - Fuel, 2 - ComputersAndAccessories, 3 - OfficeSupplies, 4 - OfficeCoffee, 5 - Other, 6 - TravelExpenses, 7 - Postage, 8 - PurchasesOfGoods, 9 - ITServiceOrSoftware, 10 - EmployeeRepresentation

<a id="schema-receiptdocumentdraft"></a>
#### `ReceiptDocumentDraft`

Meta data for handle document draft connected to receipt.

| Field | Type | Description |
|---|---|---|
| `DocumentDraftId`? | `integer(int32)` | Document draft id |
| `ReceiptId` | `integer(int32)` | Receipt id |

<a id="schema-receiptimagemeta"></a>
#### `ReceiptImageMeta`

Meta data for an image.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The image id. |
| `ContentType`? | `string` | The content type of the image. |
| `NumberOfPages` | `integer(int32)` | The number of pages the image contains. |

<a id="schema-receiptmeta"></a>
#### `ReceiptMeta`

Meta data for the image.

| Field | Type | Description |
|---|---|---|
| `NumberOfImages` | `integer(int32)` | The total number of images. |
| `Images`? | [`ReceiptImageMeta`](#schema-receiptimagemeta)[] | Collection of meta data for all the images. |

<a id="schema-receiptpaymentinfo"></a>
#### `ReceiptPaymentInfo`

| Field | Type | Description |
|---|---|---|
| `PersonNumber`? | `string` | Person number for the user who created the receipt. |
| `BankAccount`? | `string` | Bank account number the receipt should be payed out to. |
| `ClearingNumber`? | `string` | Clearing number of the bank account the receipt should be payed out to. |
| `HasMissingPaymentDetails` | `boolean` | Person doesn't have a swedish personnumber and or missing bankaccount |

<a id="schema-receiptpaymentmethod"></a>
#### `ReceiptPaymentMethod`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the payment method |
| `PersonId` | `integer(int32)` | Payment method owner's Id |
| `CanDeactivate` | `boolean` | Can payment method deactivate |
| `IsPaymentMethodTypeDisabled`? | `boolean` | Is payment method type readonly |
| `CompanyId`? | `integer(int32)` | Company id for wint card payment method types. Null for other payment method types. |
| `Name`? | `string` | Name of the payment method |
| `CurrencyMarkup`? | `number(double)` | Currency surcharge |
| `Type` | [`ReceiptPaymentMethodType`](#schema-receiptpaymentmethodtype) |  |
| `IsActive` | `boolean` | Is payment method active |

<a id="schema-receiptpaymentmethodtype"></a>
#### `ReceiptPaymentMethodType`

Enum: `BankCard`, `CreditCard`, `OwnExpense`, `Cash`, `Settlement`, `WintCard`, `MissingDocument`

<a id="schema-receiptperson"></a>
#### `ReceiptPerson`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` |  |
| `Name`? | `string` |  |
| `Company`? | `string` |  |

<a id="schema-receiptpost"></a>
#### `ReceiptPost`

| Field | Type | Description |
|---|---|---|
| `ReceiptPaymentInfo` | [`ReceiptPaymentInfo`](#schema-receiptpaymentinfo) |  |
| `DateTime` | `string(date-time)` | When the receipt was created |
| `Dimensions`? | `string(uuid)`[] | Dimensions of the receipt |
| `DimensionList`? | [`DimensionData`](#schema-dimensiondata)[] | New dimensions structure for the web app |
| `Comment`? | `string` | User comment on receipt |
| `ReceiptCategoryId`? | `integer(int32)` | Id of receipt category |
| `PaymentMethodId`? | `integer(int32)` | Id of receipt payment method |
| `Intent`? | `string` |  |
| `Amount` | `number(double)` | Ammount paid |
| `PaymentMethodType` | [`ReceiptPaymentMethodType`](#schema-receiptpaymentmethodtype) |  |
| `Persons`? | [`ReceiptPerson`](#schema-receiptperson)[] | People the receipt concerns |
| `Images`? | `string(byte)`[] |  *(deprecated)* |
| `ClientId`? | `string(uuid)` |  |
| `Currency`? | `string` | Currency of the receipt |
| `Attachments`? | [`ReceiptAttachment`](#schema-receiptattachment)[] | The attachments of the receipt. |
| `SupplierName`? | `string` | Name of the supplier. |
| `IsOtherPaymentMethod` | `boolean` | The flag indicating if the payment method is "Other" from a classified receipt that comes originally from a GenericVoucher submission. But the DocumentClassificationService has identified this document as a receipt. Please look at this user story for more information: https://app.clickup.com/t/4523827/DEV-20076 |
| `OtherPaymentMethodExplanation`? | `string` | Explanation from the user for the selection of the "Other" payment method. Will always contain a value if "IsOtherPaymentMethod" is true. |

<a id="schema-receiptput"></a>
#### `ReceiptPut`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier of the receipt. |
| `ReceiptPaymentInfo` | [`ReceiptPaymentInfo`](#schema-receiptpaymentinfo) |  |
| `DateTime` | `string(date-time)` | When the receipt was created |
| `Dimensions`? | `string(uuid)`[] | Dimensions of the receipt |
| `DimensionList`? | [`DimensionData`](#schema-dimensiondata)[] | New dimensions structure for the web app |
| `Comment`? | `string` | User comment on receipt |
| `ReceiptCategoryId`? | `integer(int32)` | Id of receipt category |
| `PaymentMethodId`? | `integer(int32)` | Id of receipt payment method |
| `Intent`? | `string` |  |
| `Amount` | `number(double)` | Ammount paid |
| `PaymentMethodType` | [`ReceiptPaymentMethodType`](#schema-receiptpaymentmethodtype) |  |
| `Persons`? | [`ReceiptPerson`](#schema-receiptperson)[] | People the receipt concerns |
| `Images`? | `string(byte)`[] |  *(deprecated)* |
| `ClientId`? | `string(uuid)` |  |
| `Currency`? | `string` | Currency of the receipt |
| `Attachments`? | [`ReceiptAttachment`](#schema-receiptattachment)[] | The attachments of the receipt. |
| `SupplierName`? | `string` | Name of the supplier. |
| `IsOtherPaymentMethod` | `boolean` | The flag indicating if the payment method is "Other" from a classified receipt that comes originally from a GenericVoucher submission. But the DocumentClassificationService has identified this document as a receipt. Please look at this user story for more information: https://app.clickup.com/t/4523827/DEV-20076 |
| `OtherPaymentMethodExplanation`? | `string` | Explanation from the user for the selection of the "Other" payment method. Will always contain a value if "IsOtherPaymentMethod" is true. |

<a id="schema-receiptputinfo"></a>
#### `ReceiptPutInfo`

Receipt specific data

| Field | Type | Description |
|---|---|---|
| `ReceiptCategoryId`? | `integer(int32)` | Id of receipt category |
| `Persons`? | [`ReceiptPerson`](#schema-receiptperson)[] | People the receipt concerns |
| `DimensionList`? | [`DimensionData`](#schema-dimensiondata)[] | New dimensions structure for the web app TODO: delete if not used in mobile app |
| `Intent`? | `string` | Concerns/Purpose of the receipt |
| `Currency`? | `string` | The currency |

<a id="schema-receiptsendbackdata"></a>
#### `ReceiptSendBackData`

Meta data for SendBack-action of a receipt.

| Field | Type | Description |
|---|---|---|
| `Message`? | `string` | Message (reason) |
| `Date`? | `string(date-time)` | When the receipt was last sent back |
| `SentBackById`? | `integer(int32)` | The id of the person who sent the receipt back |
| `SentBackByName`? | `string` | The name of the person who sent the receipt back |

<a id="schema-receiptstateapimodel"></a>
#### `ReceiptStateApiModel`

Enum: `Received`, `Booked`, `Canceled`, `WaitingAcceptance`, `Investigation`, `SentBackToCustomer`, `SentBackFromReceiptAdmin`, `PaymentSign`, `Stopped`, `PayoutRescheduled`, `Draft`, `Purchased`, `Paid`
  
_Values_: 0 - Received, 1 - Booked, 2 - Canceled, 3 - WaitingAcceptance, 4 - Investigation, 5 - SentBackToCustomer, 6 - SentBackFromReceiptAdmin, 7 - PaymentSign, 8 - Stopped, 9 - PayoutRescheduled, 10 - Draft, 100 - Purchased, 101 - Paid

<a id="schema-receiptssimilaritem"></a>
#### `ReceiptsSimilarItem`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the receipt |
| `Date`? | `string(date-time)` | Created date of the receipt |
| `Sender`? | `string` | Name of the person who uploads |
| `Amount` | `number(double)` | The total amount of the receipt |
| `State` | [`ReceiptStateApiModel`](#schema-receiptstateapimodel) |  |
| `Currency`? | `string` | The currency of the receipt |
| `RefersTo`? | `string` | Receipt category type |

<a id="schema-recurringinvoice"></a>
#### `RecurringInvoice`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the recurring invoice |
| `CustomerName`? | `string` | Name of the customer |
| `CustomerOrgNo`? | `string` | Organization number of the customer |
| `OwnerName`? | `string` | Name of the invoice owner |
| `TotalAmount` | `number(double)` | The total amount with vat |
| `TotalTax` | `number(double)` | The tax amount |
| `IsEUCustomer` | `boolean` | If customer is EU Customer |
| `NumberOfSentInvoices` | `integer(int32)` | Number of completed invoices |
| `NumberOfPlannedInvoices` | `integer(int32)` | Number of planned invoices until the end date or null if there is no end date. |
| `ExpectedRevenue` | `number(double)` | Expected revenue from this recurring invoice. If the end date is not set then the revenue for 12 months. |
| `Status` | [`RecurringInvoiceState`](#schema-recurringinvoicestate) |  |
| `InvoicePaymentBgNumber`? | `string` | Bankgiro number of the payment |
| `InvoicePaymentMethod` | [`InvoicePaymentMethod`](#schema-invoicepaymentmethod) |  |
| `RevenueFromPastInvoices`? | `number(double)` | Revenue from invoices created from this recurring invoice |
| `RecurringInvoiceVersion` | [`RecurringInvoiceVersion`](#schema-recurringinvoiceversion) |  |
| `TotalAmountSummary`? | [`CurrencyValue`](#schema-currencyvalue)[] | Sum of total amount values group by currency (Used only when the filter is configured with IncludeSummary) |
| `TotalRevenueFromPastInvoicesSummary`? | [`CurrencyValue`](#schema-currencyvalue)[] | Sum of revenue from past invoices group by currency (Used only when the filter is configured with IncludeSummary) |
| `Attachments`? | [`InvoiceAttachment`](#schema-invoiceattachment)[] | List of invoice attachments. |
| `CustomerId` | `integer(int32)` | Id of the customer. |
| `OwnerId`? | `integer(int32)` | Id of the owner. |
| `CustomerReference` | [`InvoiceReference`](#schema-invoicereference) |  |
| `ContactPerson`? | `string` | Seller reference. |
| `Notes`? | `string` | Text data that you want to include in the projected invoices. |
| `Dimensions`? | `string(uuid)`[] | The dimensions for the invoice. |
| `FirstPostingDate` | `string(date-time)` | The posting date of the recurring invoice. |
| `StopDate`? | `string(date-time)` | The stop date of the recurring invoice. |
| `ShowReferencePersonInAddress` | `boolean` | Whether the invoice should have the reference name in the address. |
| `ShowShippingAddress` | `boolean` | Whether the invoice should contain the customers' delivery address. |
| `ShowCurrencyCode` | `boolean` | Whether the invoice should show the currency or not. |
| `Language`? | `string` | The language of the invoice. Either SV or EN. |
| `Currency`? | `string` | The currency of the invoice E.g. SEK. |
| `PaymentTerms` | `integer(int32)` | Payment terms for the invoice. |
| `PaymentOptionId`? | `integer(int32)` | ID of the PaymentOption to use. |
| `DaysToDelivery`? | `integer(int32)` | Number of days to delivery in relation to invoice date. Value can be negative. |
| `Rows` | [`RecurringInvoiceRow`](#schema-recurringinvoicerow)[] | The rows for the invoice. |
| `Template` | [`InvoicePdfTemplate`](#schema-invoicepdftemplate) |  |
| `RecurringDescription`? | `string` | Description for the recurring invoice. |
| `InvoiceFrequency` | [`RecurringInvoiceFrequency`](#schema-recurringinvoicefrequency) |  |
| `UntilFurtherNotice` | `boolean` | Whether invoice will continue until further notice. |
| `InvoiceSendType` | [`InvoiceSendType`](#schema-invoicesendtype) |  |
| `MailFromType` | [`SendRecurringInvoiceMailsFromEnum`](#schema-sendrecurringinvoicemailsfromenum) |  |
| `MailToType` | [`SendInvoiceMailsToEnum`](#schema-sendinvoicemailstoenum) |  |
| `MailMessage`? | `string` | Message body of the email. |
| `MailTitle`? | `string` | Subject of the email. |
| `MailTo`? | `string` | Email recipient. |
| `RecurringInvoiceSendType` | [`RecurringInvoiceSendType`](#schema-recurringinvoicesendtype) |  |

<a id="schema-recurringinvoicefrequency"></a>
#### `RecurringInvoiceFrequency`

Enum: `Monthly`, `Quarterly`, `HalfYearly`, `Yearly`
  
_Values_: 0 - Monthly, 1 - Quarterly, 2 - HalfYearly, 3 - Yearly

<a id="schema-recurringinvoicerow"></a>
#### `RecurringInvoiceRow`

| Field | Type | Description |
|---|---|---|
| `Guid` | `string(uuid)` | Id of the row. |
| `ArticleId`? | `integer(int32)` | The id of the article this invoice row is referring to. |
| `Quantity` | `number(double)` | The quantity for this row. |
| `Description`? | `string` | The description of the row. If article is set, the description will be the article's text. |
| `OverriddenDescription`? | `string` | Set this if you want to select an article but modify the article's text. |
| `Unit` | [`Unit`](#schema-unit) |  |
| `UnitPrice`? | `number(double)` | The unit price. If article is set, this property will be ignored. |
| `OverriddenUnitPrice`? | `number(double)` | Set this if you want to select an article but modify the price. |
| `OrderIndex` | `integer(int32)` | Zero-based index. |
| `Rot` | `boolean` | If invoice row is ROT. Invoice cannot both contain ROT and RUT invoice rows. |
| `Rut` | `boolean` | If invoice row is RUT. Invoice cannot both contain ROT and RUT invoice rows. |
| `Vat` | `number(double)` | The VAT percentage. |
| `OverriddenVat`? | `number(double)` | Set this if you want to select an article but modify the VAT percentage. |
| `EuVatProductType` | [`EuVatProductType`](#schema-euvatproducttype) |  |
| `Periodisation` | `boolean` | Whether the invoice row should be booked with a periodisation. If so Wint.Superkoll.API.Model.RecurringInvoiceRow.PeriodisationStartOffset and Wint.Superkoll.API.Model.RecurringInvoiceRow.PeriodisationLength must be set. |
| `PeriodisationStartOffset` | `integer(int32)` | Starting month in relation to the invoice month. (-) means before invoice month and (+) means after invoice month. Default will be set to 0. |
| `PeriodisationLength` | `integer(int32)` | Duration of the periodisation.Defaut will be set to the recurring interval. |
| `Dimensions`? | `string(uuid)`[] | The dimensions for the row. |

<a id="schema-recurringinvoicesendtype"></a>
#### `RecurringInvoiceSendType`

Enum: `Manual`, `Auto`
  
_Values_: 0 - Manual, 1 - Auto

<a id="schema-recurringinvoicestate"></a>
#### `RecurringInvoiceState`

Enum: `Created`, `Ongoing`, `Stopped`
  
_Values_: 0 - Created, 1 - Ongoing, 2 - Stopped

<a id="schema-recurringinvoiceversion"></a>
#### `RecurringInvoiceVersion`

Enum: `V0_Old`, `V1_PeriodInfo`

<a id="schema-reference"></a>
#### `Reference`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The id of the reference person. Will be returned when GET:ing the customer This should not be set when creating a customer. |
| `CustomerId` | `integer(int32)` | Customer Id |
| `Name` | `string` | The name of the reference person |
| `EmailAddress`? | `string` | The email address of the reference person |
| `Phone`? | `string` | The phone number to the reference person |
| `ReferenceIdentifier`? | `string` | The reference identifier associated with a reference person. Included in e-invoicing for sender validation. |
| `IsDefault` | `boolean` | If the reference person to be used as default for the customer |

<a id="schema-referencepersonimport"></a>
#### `ReferencePersonImport`

| Field | Type | Description |
|---|---|---|
| `ReferenceNameColumn`? | `string` | CSV column for reference person's name. |
| `ReferenceMailColumn`? | `string` | CSV column for reference person's email. |
| `ReferencePhoneColumn`? | `string` | CSV column for reference person's phone. |
| `ReferenceIdentifierColumn`? | `string` | CSV column for reference person's identifier. |
| `ReferenceIsDefaultColumn`? | `string` | CSV column for if reference person isDefault. |

<a id="schema-referencepost"></a>
#### `ReferencePost`

| Field | Type | Description |
|---|---|---|
| `CustomerId` | `integer(int32)` | Customer Id |
| `Name` | `string` | The name of the reference person |
| `EmailAddress`? | `string` | The email address of the reference person |
| `Phone`? | `string` | The phone number to the reference person |
| `ReferenceIdentifier`? | `string` | The reference identifier associated with a reference person. Included in e-invoicing for sender validation. |
| `IsDefault` | `boolean` | If the reference person to be used as default for the customer |

<a id="schema-referenceput"></a>
#### `ReferencePut`

| Field | Type | Description |
|---|---|---|
| `Name` | `string` | The name of the reference person |
| `EmailAddress`? | `string` | The email address of the reference person |
| `Phone`? | `string` | The phone number to the reference person |
| `ReferenceIdentifier`? | `string` | The reference identifier associated with a reference person. Included in e-invoicing for sender validation. |
| `IsDefault` | `boolean` | If the reference person to be used as default for the customer |

<a id="schema-referencesearchresponse"></a>
#### `ReferenceSearchResponse`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the reference person |
| `Name`? | `string` | Name of the reference person |
| `Mail`? | `string` | Email of the reference person |
| `ReferenceIdentifier`? | `string` | The reference identifier associated with a reference person. Included in e-invoicing for sender validation. |

<a id="schema-regeneratemonthlyreportrequest"></a>
#### `RegenerateMonthlyReportRequest`

Asks for another generation pass over an existing report.

| Field | Type | Description |
|---|---|---|
| `KaFeedback`? | `string` | Optional free-text feedback threaded into the next pass. Omit for a plain rerun. |
| `Deployment`? | `string` | Optional model override. Omit to reuse the previous pass's model. |
| `DiscardPriorMarkdown` | `boolean` | When true, the previous body is not fed to the model, so the pass starts from the data alone. |

<a id="schema-reportpaymentrequest"></a>
#### `ReportPaymentRequest`

| Field | Type | Description |
|---|---|---|
| `PaymentDate` | `string(date-time)` | The payment date for the invoice |

<a id="schema-reportsubmissiondata"></a>
#### `ReportSubmissionData`

Information needed to submit the salary deviation report

| Field | Type | Description |
|---|---|---|
| `YearMonth` | `integer(int32)` | Year and month of the deviation report |

<a id="schema-resetpassword"></a>
#### `ResetPassword`

| Field | Type | Description |
|---|---|---|
| `Ticket`? | `string` |  |
| `Password`? | `string` |  |
| `ConfirmPassword`? | `string` |  |

<a id="schema-revenuereportapproval"></a>
#### `RevenueReportApproval`

A revenue reporting period approval for a template (payment method).

| Field | Type | Description |
|---|---|---|
| `TemplateId` | `string(uuid)` | Identifier of the template (payment method) the approval belongs to. |
| `PeriodYear` | `integer(int32)` | Reporting period year of the approval. |
| `PeriodMonth` | `integer(int32)` | Reporting period month of the approval. |
| `PeriodStartDay`? | `integer(int32)` | Start day of the reporting period the approval covers. Only set for weekly templates, where several periods share a year and month. Null means the approval covers the whole month, which is the case for every monthly or longer template and for approvals recorded before DEV-27884. |
| `IsApproved` | `boolean` | Whether the period is approved. |
| `ApprovedBy`? | `integer(int32)` | Identifier of the person who approved the period. |
| `ApprovedDate`? | `string(date-time)` | Date the period was approved. |
| `ConfirmedNoIncome` | `boolean` | Whether the approval confirmed the period had no income. |
| `Comment`? | `string` | Optional comment on the approval. |
| `AttachmentFileName`? | `string` | Name of the approval's attachment file, if any. |
| `AttachmentContentType`? | `string` | Content type of the approval's attachment, e.g. image/png, application/pdf. |

<a id="schema-revenuereportapproverequest"></a>
#### `RevenueReportApproveRequest`

Post object to approve a revenue reporting period for a template (payment method).

| Field | Type | Description |
|---|---|---|
| `TemplateId` | `string(uuid)` | Identifier of the template (payment method) the period belongs to. |
| `PeriodYear` | `integer(int32)` | Reporting period year being approved. |
| `PeriodMonth` | `integer(int32)` | Reporting period month being approved. |
| `PeriodStartDay`? | `integer(int32)` | Start day of the reporting period being approved. Only meaningful for weekly templates, where several periods share a year and month. Leave null to approve the whole month, which is what every monthly or longer template does and what callers predating DEV-27884 did. |
| `ConfirmNoIncome` | `boolean` | Confirmation that the period had no income when no report was submitted for it. |
| `Comment`? | `string` | Optional comment for the approval. |
| `Attachment` | [`RevenueReportAttachment`](#schema-revenuereportattachment) |  |
| `Attachments`? | [`RevenueReportAttachment`](#schema-revenuereportattachment)[] | Optional image/PDF attachments supporting the approval ("kompletterande underlag"). Each one becomes its own unbooked accounting voucher the accountant can open from the period's todo. |

<a id="schema-revenuereportattachment"></a>
#### `RevenueReportAttachment`

A revenue report attachment which will be an image or PDF.

| Field | Type | Description |
|---|---|---|
| `ContentType`? | `string` | Attachment content type e.g. application/pdf, image/png, ... |
| `Data`? | `string(byte)` | Attachment data. |
| `FileName`? | `string` | The name of the file. |

<a id="schema-revenuereportattachmentinfo"></a>
#### `RevenueReportAttachmentInfo`

Metadata of a revenue report attachment (without the file data).

| Field | Type | Description |
|---|---|---|
| `Id`? | `string` | Identifier of the attachment. |
| `FileName`? | `string` | Name of the attached file. |
| `ContentType`? | `string` | Content type of the attached file, e.g. image/png, application/pdf. |

<a id="schema-revenuereportdescriptor"></a>
#### `RevenueReportDescriptor`

Compact details of a submitted revenue report.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier of the report. |
| `Date` | `string(date-time)` | Reporting date of the report. |
| `OwnerId`? | `integer(int32)` | Identifier of the person who registered the report. |
| `OwnerName`? | `string` | Name of the person who registered the report. |
| `TemplateId` | `string(uuid)` | Identifier of the template (payment method) the report was created from. |
| `TemplateName`? | `string` | Display name of the template (payment method) the report was created from. |
| `CostCenter`? | `string` | Cost center dimension's short name of the report's sales. |
| `Project`? | `string` | Project dimension's short name of the report's sales. |
| `Difference` | `number(double)` | Difference in sales and payments in SEK. |
| `Amount` | `number(double)` | Total sales amount of the report in SEK. |
| `Status` | [`RevenueReportStatus`](#schema-revenuereportstatus) |  |

<a id="schema-revenuereportdetail"></a>
#### `RevenueReportDetail`

Full details of a submitted revenue report.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier of the report. |
| `Date` | `string(date-time)` | Reporting date of the report. |
| `OwnerId`? | `integer(int32)` | Identifier of the person who registered the report. |
| `OwnerName`? | `string` | Name of the person who registered the report. |
| `TemplateId` | `string(uuid)` | Identifier of the template (payment method) the report was created from. |
| `TemplateName`? | `string` | Display name of the template (payment method) the report was created from. |
| `Status` | [`RevenueReportStatus`](#schema-revenuereportstatus) |  |
| `Difference` | `number(double)` | Difference in sales and payments in SEK. |
| `Amount` | `number(double)` | Total sales amount of the report in SEK. |
| `Comment`? | `string` | Optional comment on the report. |
| `Items`? | [`RevenueReportItemDto`](#schema-revenuereportitemdto)[] | Account based transactions of the report. |
| `Attachments`? | [`RevenueReportAttachmentInfo`](#schema-revenuereportattachmentinfo)[] | Image/PDF attachments of the report. |

<a id="schema-revenuereportdto"></a>
#### `RevenueReportDto`

Post object to submit a revenue report.

| Field | Type | Description |
|---|---|---|
| `TemplateId` | `string(uuid)` | Identifier of the template the report is based on. |
| `Date` | `string(date-time)` | Booking date of the report. |
| `PeriodYear` | `integer(int32)` | Reporting period year. |
| `PeriodMonth` | `integer(int32)` | Reporting period month. |
| `PeriodStartDay`? | `integer(int32)` | Ignored. For a weekly template the reported period is resolved from Wint.Superkoll.API.Model.RevenueReportDto.Date against the template's own schedule, because a caller cannot know where the weekly grid falls, and for monthly and longer templates the period is the year and month above. |
| `Comment`? | `string` | Optional comment for the report. |
| `Items`? | [`RevenueReportItemDto`](#schema-revenuereportitemdto)[] | Account based transactions for the report. |
| `Attachments`? | [`RevenueReportAttachment`](#schema-revenuereportattachment)[] | Image attachments (images, PDFs) for the report. |

<a id="schema-revenuereportitemcategory"></a>
#### `RevenueReportItemCategory`

Enum: `Sales`, `PaymentMethod`, `Other`

<a id="schema-revenuereportitemdto"></a>
#### `RevenueReportItemDto`

Account based transaction in a revenue report.

| Field | Type | Description |
|---|---|---|
| `TemplateItemId`? | `string(uuid)` | Identifier of the template item this transaction maps to. |
| `Account` | `integer(int32)` | Account number of the transaction. |
| `Amount` | `number(double)` | Amount of the transaction. |
| `VatAccount`? | `integer(int32)` | VAT account number of the transaction. |
| `VatRate`? | `number(double)` | VAT rate of the transaction. |
| `AccountType` | [`RevenueReportItemType`](#schema-revenuereportitemtype) |  |
| `Category` | [`RevenueReportItemCategory`](#schema-revenuereportitemcategory) |  |
| `Description`? | `string` | Description of the transaction. |
| `CostCenter`? | `string` | Cost center dimension's short name. |
| `Project`? | `string` | Project dimension's short name. |

<a id="schema-revenuereportitemtype"></a>
#### `RevenueReportItemType`

Enum: `Debit`, `Credit`

<a id="schema-revenuereportstatus"></a>
#### `RevenueReportStatus`

Enum: `Reported`, `Voided`

<a id="schema-revenuereportingtemplate"></a>
#### `RevenueReportingTemplate`

Company revenue reporting template.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier of the template. |
| `Name`? | `string` | Display name of the template. |
| `IsVatAffecting` | `boolean` | Whether the template affects VAT reporting. |
| `RequiresAttachment` | `boolean` | Whether a report created from this template must carry at least one attachment. The revenue reporting service enforces this when the report is created and rejects a report without attachments, so clients should block submission before that point. Defaults to `true` so a template created before the flag existed keeps the requirement. |
| `Items`? | [`RevenueReportingTemplateItem`](#schema-revenuereportingtemplateitem)[] | Template items used to build a report. |

<a id="schema-revenuereportingtemplateitem"></a>
#### `RevenueReportingTemplateItem`

Company revenue reporting template item.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier of the template item. |
| `Account` | `integer(int32)` | Account number for the template item. |
| `Category` | [`RevenueReportItemCategory`](#schema-revenuereportitemcategory) |  |
| `AccountType` | [`RevenueReportItemType`](#schema-revenuereportitemtype) |  |
| `VatAccount`? | `integer(int32)` | VAT account number for the template item. |
| `VatRate`? | `number(double)` | VAT rate for the template item. |
| `Description`? | `string` | Description for the template item. |
| `SortOrder` | `integer(int32)` | Sort order for the template item. |

<a id="schema-rutrotworktype"></a>
#### `RutRotWorkType`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of work type |
| `Name`? | `string` | Name of work type |
| `Type` | [`InvoiceHouseWorkType`](#schema-invoicehouseworktype) |  |

<a id="schema-siefilepost"></a>
#### `SIEFilePost`

| Field | Type | Description |
|---|---|---|
| `Data`? | `string(byte)` | The data of the attachment. |
| `ContentType`? | `string` | The content type of the file. |
| `Name`? | `string` | The name of the file. |
| `Comment`? | `string` | Comment for SIEFile |

<a id="schema-salaryadminsearchinfo"></a>
#### `SalaryAdminSearchInfo`

Information of the salary admin

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of the salary admin |
| `Name`? | `string` | Name of the salary admin |

<a id="schema-salarydeviation"></a>
#### `SalaryDeviation`

Salary deviation GET

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Salary deviation's unique Id |
| `PersonId` | `integer(int32)` | Id of the employee |
| `PersonName`? | `string` | Name of the employee |
| `IsDeviationOngoing` | `boolean` | Indicate whether deviation is on going |
| `HasConnectedTimeReports` | `boolean` | Indicate whether deviation can only be handled by time reporting |
| `IsAdminOnlyType` | `boolean` | Indicate that the deviation type is only editable by admin users |
| `YearAndMonth` | `integer(int32)` | Year and month e.g. YYYYMM |
| `Comment`? | `string` | Comment |
| `FromDate`? | `string(date-time)` | Start date |
| `ToDate`? | `string(date-time)` | End date |
| `Distance`? | `integer(int32)` | Journey distance |
| `DayHours`? | [`SalaryDeviationHoursByDay`](#schema-salarydeviationhoursbyday)[] | List of days and hours information |
| `DeviationType` | [`SalaryDeviationType`](#schema-salarydeviationtype) |  |
| `ChildName`? | `string` | Name of the child |
| `Country`? | `string` | Two letters country code |
| `VehicleType` | [`SalaryDeviationVehicleType`](#schema-salarydeviationvehicletype) |  |
| `MealDeductions`? | [`SalaryDeviationDeviationMeal`](#schema-salarydeviationdeviationmeal)[] | List of days and meal information |
| `Hours`? | `number(double)` | Hours reported |
| `Provisions`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of provisions |
| `CommissionsVacationPaid`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commissions vacation paid |
| `CommissionsVacationSaved`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commissions vacation saved |
| `CommissionWithdrawalsSavedVacation`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commission withdrawals saved vacation |
| `Bonus`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of Bonus |
| `CustomDeviationCompensation`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of custom compensations |
| `CustomDeviationName`? | `string` | Name of the custom deviation. |

<a id="schema-salarydeviationdescriptor"></a>
#### `SalaryDeviationDescriptor`

Compact details of salary deviation

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Salary deviation's unique Id |
| `PersonId` | `integer(int32)` | Id of the employee |
| `PersonName`? | `string` | Name of the employee |
| `DeviationType` | [`SalaryDeviationType`](#schema-salarydeviationtype) |  |
| `Comment`? | `string` | Comment |
| `FromDate`? | `string(date-time)` | Start date |
| `ToDate`? | `string(date-time)` | End date |
| `YearAndMonth` | `integer(int32)` | Year and month e.g. YYYYMM |
| `Summary` | [`DeviationSummary`](#schema-deviationsummary) |  |
| `MonthState` | [`SalaryDeviationMonthState`](#schema-salarydeviationmonthstate) |  |
| `HasDeviationsForPeriod`? | `boolean` | Whether this person has deviations |
| `CustomDeviationName`? | `string` | Name of the custom deviation |
| `IsAdminOnlyType` | `boolean` | Indicate that the deviation type is only editable by admin users |

<a id="schema-salarydeviationdeviationmeal"></a>
#### `SalaryDeviationDeviationMeal`

Meals information by a date item

| Field | Type | Description |
|---|---|---|
| `Day` | `string(date-time)` | Specific Date |
| `Breakfast` | `boolean` | Is breakfast included |
| `Lunch` | `boolean` | Is lunch included |
| `Dinner` | `boolean` | Is Dinner included |

<a id="schema-salarydeviationhoursbyday"></a>
#### `SalaryDeviationHoursByDay`

Hours for a date item

| Field | Type | Description |
|---|---|---|
| `Day` | `string(date-time)` | Specific Date |
| `Hours` | `number(double)` | Number of hours per the date |

<a id="schema-salarydeviationmonth"></a>
#### `SalaryDeviationMonth`

Company salary deviation month

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Id of salary deviation month |
| `YearAndMonth` | `integer(int32)` | Year and month e.g. YYYYMM |
| `State` | [`SalaryDeviationMonthState`](#schema-salarydeviationmonthstate) |  |
| `Comment`? | `string` | Comment on the month |

<a id="schema-salarydeviationmonthstate"></a>
#### `SalaryDeviationMonthState`

Enum: `Created`, `Submitted`, `Handled`

<a id="schema-salarydeviationpost"></a>
#### `SalaryDeviationPost`

Salary deviation POST item

| Field | Type | Description |
|---|---|---|
| `PersonId` | `integer(int32)` | Employee Id |
| `FromTime`? | `string` | Start time |
| `ToTime`? | `string` | End time |
| `YearAndMonth` | `integer(int32)` | Year and month e.g. YYYYMM |
| `Comment`? | `string` | Comment |
| `FromDate`? | `string(date-time)` | Start date |
| `ToDate`? | `string(date-time)` | End date |
| `Distance`? | `integer(int32)` | Journey distance |
| `DayHours`? | [`SalaryDeviationHoursByDay`](#schema-salarydeviationhoursbyday)[] | List of days and hours information |
| `DeviationType` | [`SalaryDeviationType`](#schema-salarydeviationtype) |  |
| `ChildName`? | `string` | Name of the child |
| `Country`? | `string` | Two letters country code |
| `VehicleType` | [`SalaryDeviationVehicleType`](#schema-salarydeviationvehicletype) |  |
| `MealDeductions`? | [`SalaryDeviationDeviationMeal`](#schema-salarydeviationdeviationmeal)[] | List of days and meal information |
| `Hours`? | `number(double)` | Hours reported |
| `Provisions`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of provisions |
| `CommissionsVacationPaid`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commissions vacation paid |
| `CommissionsVacationSaved`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commissions vacation saved |
| `CommissionWithdrawalsSavedVacation`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commission withdrawals saved vacation |
| `Bonus`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of Bonus |
| `CustomDeviationCompensation`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of custom compensations |
| `CustomDeviationName`? | `string` | Name of the custom deviation. |

<a id="schema-salarydeviationput"></a>
#### `SalaryDeviationPut`

Salary deviation PUT item

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | Salary deviation's unique Id |
| `PersonId` | `integer(int32)` | Employee Id |
| `FromTime`? | `string` | Start time |
| `ToTime`? | `string` | End time |
| `YearAndMonth` | `integer(int32)` | Year and month e.g. YYYYMM |
| `Comment`? | `string` | Comment |
| `FromDate`? | `string(date-time)` | Start date |
| `ToDate`? | `string(date-time)` | End date |
| `Distance`? | `integer(int32)` | Journey distance |
| `DayHours`? | [`SalaryDeviationHoursByDay`](#schema-salarydeviationhoursbyday)[] | List of days and hours information |
| `DeviationType` | [`SalaryDeviationType`](#schema-salarydeviationtype) |  |
| `ChildName`? | `string` | Name of the child |
| `Country`? | `string` | Two letters country code |
| `VehicleType` | [`SalaryDeviationVehicleType`](#schema-salarydeviationvehicletype) |  |
| `MealDeductions`? | [`SalaryDeviationDeviationMeal`](#schema-salarydeviationdeviationmeal)[] | List of days and meal information |
| `Hours`? | `number(double)` | Hours reported |
| `Provisions`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of provisions |
| `CommissionsVacationPaid`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commissions vacation paid |
| `CommissionsVacationSaved`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commissions vacation saved |
| `CommissionWithdrawalsSavedVacation`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of commission withdrawals saved vacation |
| `Bonus`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of Bonus |
| `CustomDeviationCompensation`? | [`SumDescriptionDto`](#schema-sumdescriptiondto)[] | List of custom compensations |
| `CustomDeviationName`? | `string` | Name of the custom deviation. |

<a id="schema-salarydeviationputpoststatus"></a>
#### `SalaryDeviationPutPostStatus`

Status of Salary deviation Put and Post operation

| Field | Type | Description |
|---|---|---|
| `Succeeded` | `boolean` | Whether the operation is successfully completed or not |
| `ErrorMessage`? | `string` | Detailed error |
| `Id` | `integer(int32)` | Id of salary deviation instance |

<a id="schema-salarydeviationtype"></a>
#### `SalaryDeviationType`

Enum: `Vacation`, `CareOfChildren`, `Sick`, `ParentalLeave`, `Absence`, `WithdrawalCompensation`, `DepositedCompensation`, `WorkedHours`, `Allowance`, `AllowanceForeign`, `CommissionFee`, `Bonus`, `Mileage`, `TenDays`, `CommissionVacationPaid`, `CommissionVacationSaved`, `WithdrawalsSavedVacation`, `CustomDeviationCompensation`, `CustomTimeDeviation`, `Overtime50`, `Overtime75`, `Overtime100`, `Overtime150`, `Overtime200`, `OvertimeSimple`, `OvertimeQualified`, `ExtraTime`, `UnsocialWorkingHours1`, `UnsocialWorkingHours2`, `UnsocialWorkingHours3`, `UnsocialWorkingHours4`, `OnCall`, `Preparedness`, `Overtime30`, `TravelTimeSimple`, `TravelTimeQualified`, `ReducedWorkingHours`, `PaidShortTermLeave`

<a id="schema-salarydeviationvehicletype"></a>
#### `SalaryDeviationVehicleType`

Enum: `OwnCar`, `CompanyDiesel`, `CompanyGasoline`, `CompanyElectric`

<a id="schema-salarydraft"></a>
#### `SalaryDraft`

The projected payroll payout for the year and month period, together with related messages between the customer salary admins and the house salary team

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The resource id |
| `Owner_Id`? | `integer(int32)` | The current salary draft todo assignee |
| `OwnerName`? | `string` | The current salary draft todo assignee |
| `YearAndMonth` | `integer(int32)` | The salary draft Wint.Superkoll.API.Model.SalaryDraft.YearAndMonth, denoting the period the salary draft concerns. |
| `CreatedAt`? | `string(date-time)` | When the resource was created |
| `State` | [`SalaryDraftState`](#schema-salarydraftstate) |  |
| `Messages`? | [`SalaryDraftMessage`](#schema-salarydraftmessage)[] | The collection of messages in the dialogue related to the salary draft |
| `Attachments`? | [`SalaryDraftAttachment`](#schema-salarydraftattachment)[] | The collection of draft documents detailing the projected payroll payout |
| `ApprovedDate`? | `string(date-time)` | The date the salary draft approved |

<a id="schema-salarydraftassignaction"></a>
#### `SalaryDraftAssignAction`

Information related to salary draft assign action

| Field | Type | Description |
|---|---|---|
| `SalaryDraftAssigneeId` | `integer(int32)` | Id of the person who is receiving salary draft |
| `Message`? | `string` | Reason message the action |

<a id="schema-salarydraftattachment"></a>
#### `SalaryDraftAttachment`

A draft document detailing the projected payroll payout.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The resource id. |
| `Data`? | `string(byte)` | The attachment data. |
| `Name`? | `string` | The name of the attached document. |
| `ContentType`? | `string` | The content type of the attached document. |

<a id="schema-salarydraftmessage"></a>
#### `SalaryDraftMessage`

Component of a dialogue related to the salary draft.

| Field | Type | Description |
|---|---|---|
| `CreatedBy_Id` | `integer(int32)` | The message creator id. |
| `CreatedBy`? | `string` | The message creator name. |
| `Text`? | `string` | The message content. |
| `Timestamp` | `string(date-time)` | When the message was created. |
| `CreatedByWint` | `boolean` | Whether message was created by Wint |

<a id="schema-salarydraftput"></a>
#### `SalaryDraftPut`

Used for reassigning the salary draft todo to a salary administrator colleague or for approving or rejecting the draft. Combining those two use cases is allowed only when rejecting the draft.

| Field | Type | Description |
|---|---|---|
| `State` | [`SalaryDraftState`](#schema-salarydraftstate) |  |
| `Message`? | `string` | Required motivation when rejecting salary drafts, ignored for all other state changes. |
| `OwnerId`? | `integer(int32)` | Salary draft assignee person id. Has to have salary administrator authority. Zero or lower is ignored. |

<a id="schema-salarydraftrejectaction"></a>
#### `SalaryDraftRejectAction`

Used to reject the salary draft

| Field | Type | Description |
|---|---|---|
| `Message`? | `string` | Reject reason message |

<a id="schema-salarydraftstate"></a>
#### `SalaryDraftState`

Enum: `NotSent`, `AtCustomer`, `Rejected`, `Approved`, `Handled`, `Removed`

<a id="schema-salaryimportfile"></a>
#### `SalaryImportFile`

| Field | Type | Description |
|---|---|---|
| `FileName`? | `string` | Name |
| `ContentType`? | `string` | Content type |
| `Data`? | `string(byte)` | File data |

<a id="schema-searchcustomerinformationresponse"></a>
#### `SearchCustomerInformationResponse`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Name of the customer |
| `OrgNr`? | `string` | Organization number of the customer |
| `City`? | `string` | Registered city of the customer |
| `ZipCode`? | `string` | Registered zipcode of the customer |
| `Street`? | `string` | Registered street of the customer |

<a id="schema-searchentitytype"></a>
#### `SearchEntityType`

Enum: `Supplier`, `Customer`, `Employee`, `Article`, `IncomingInvoices`, `CustomerInvoices`, `Receipts`
  
_Values_: 0 - Supplier, 1 - Customer, 2 - Employee, 3 - Article, 4 - IncomingInvoices, 5 - CustomerInvoices, 6 - Receipts

<a id="schema-searchresponseitems"></a>
#### `SearchResponseItems`

| Field | Type | Description |
|---|---|---|
| `Type` | [`SearchEntityType`](#schema-searchentitytype) |  |
| `EntityId`? | `string` | Entity id |
| `EntityName`? | `string` | Entity name |
| `Description`? | `string` | Description of the entity (Only set for IncomingInvoices, CustomerInvoices and Receipts. E.g: Serial number of a customer invoice) |

<a id="schema-selfinvoice"></a>
#### `SelfInvoice`

Represents the invoice data transfer object.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Gets or sets the id of the invoice. |
| `DraftInvoiceId`? | `integer(int32)` | Gets or sets the id of a draft invoice created by the self invoice. |
| `State` | [`SelfInvoiceState`](#schema-selfinvoicestate) |  |
| `CustomerId`? | `integer(int32)` | Gets or sets the identifier of the customer associated with the invoice. |
| `CustomerName`? | `string` | Gets or sets the name of the customer associated with the invoice. |
| `CustomerOrgNr`? | `string` | Gets or sets the organization number of the customer associated with the invoice. |
| `Images`? | [`SelfInvoiceImageData`](#schema-selfinvoiceimagedata)[] | Gets or sets the image data of the invoice draft. |
| `ReceivedDate` | `string(date-time)` | Gets or sets the date when the self invoice is received at wint. |
| `InvoiceDate`? | `string(date-time)` | Gets or sets the invoice date. |
| `DueDate`? | `string(date-time)` | Gets or sets the date the invoice is due. |
| `CustomerVatNumber`? | `string` | Gets or sets the customer VAT number. |
| `OCRNumber`? | `integer(int64)` | Gets or sets the OCR number. |
| `TotalAmountExVat`? | `number(double)` | Gets or sets the Total amount excluding VAT. |
| `TotalVatAmount`? | `number(double)` | Gets or sets the Total VAT amount. |
| `TotalAmount`? | `number(double)` | Gets or sets the Total amount. |
| `Currency`? | `string` | Gets or sets the currency of the invoice. |
| `Items`? | [`SelfInvoiceInvoiceItem`](#schema-selfinvoiceinvoiceitem)[] | Gets or sets the items on the invoice. |

<a id="schema-selfinvoiceimagedata"></a>
#### `SelfInvoiceImageData`

Represents the image data data transfer object.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Gets or sets the id of the image data. |
| `Content`? | `string(byte)` | Gets or sets the url of the image data. |
| `ContentType`? | `string` | Gets or sets the content type of the image data. |

<a id="schema-selfinvoiceimagedatapost"></a>
#### `SelfInvoiceImageDataPost`

| Field | Type | Description |
|---|---|---|
| `FileName`? | `string` | Gets or sets the file name of the image |
| `Content`? | `string(byte)` | Gets or sets the url of the image data. |
| `ContentType`? | `string` | Gets or sets the content type of the image data. |

<a id="schema-selfinvoiceinvoiceitem"></a>
#### `SelfInvoiceInvoiceItem`

Represents the invoice item data transfer object.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Gets or sets the id of the invoice item. |
| `Text`? | `string` | Gets or sets the text of the invoice item. |
| `Unit` | [`Unit`](#schema-unit) |  |
| `Quantity`? | `number(double)` | Gets or sets the quantity of the invoice item. |
| `UnitPrice`? | `number(double)` | Gets or sets the unit price of the invoice item. |
| `VatAmount` | `number(double)` | Gets or sets the VAT amount of the invoice item. |
| `VatRate` | `number(double)` | Gets or sets the VAT percentage of the invoice item. |
| `TotalAmountExVAT` | `number(double)` | Gets or sets the total amount excluding VAT of the invoice item. |

<a id="schema-selfinvoiceresponse"></a>
#### `SelfInvoiceResponse`

Represents the response object that contains a list of self invoices.

| Field | Type | Description |
|---|---|---|
| `Invoices`? | [`SelfInvoice`](#schema-selfinvoice)[] | Gets or sets the items in the response. |

<a id="schema-selfinvoicestate"></a>
#### `SelfInvoiceState`

Enum: `Unhandled`, `Created`, `Rejected`, `Deleted`, `ApprovedToSendToCustomer`

<a id="schema-sendinvoicemailsfromenum"></a>
#### `SendInvoiceMailsFromEnum`

Enum: `PersonMail`, `CompanyMail`, `Superkoll`

<a id="schema-sendinvoicemailstoenum"></a>
#### `SendInvoiceMailsToEnum`

Enum: `CustomerCompany`, `ReferencePerson`, `Other`

<a id="schema-sendrecurringinvoicemailsfromenum"></a>
#### `SendRecurringInvoiceMailsFromEnum`

Enum: `CompanyMail`, `Superkoll`
  
_Values_: 1 - CompanyMail, 2 - Superkoll

<a id="schema-showvouchertypes"></a>
#### `ShowVoucherTypes`

Enum: `All`, `OnlyRemoved`, `OnlyNotRemoved`, `OnlyReplacements`, `OnlyNotRemovedSameDay`
  
_Values_: 0 - All, 1 - OnlyRemoved, 2 - OnlyNotRemoved, 3 - OnlyReplacements, 4 - OnlyNotRemovedSameDay

<a id="schema-sumdescriptiondto"></a>
#### `SumDescriptionDto`

Shared class to input Sum and Description used for Bonus, Provision and Commission deviation types

| Field | Type | Description |
|---|---|---|
| `Sum` | `number(double)` | Sum |
| `Description`? | `string` | Description |

<a id="schema-superkollsalarytype"></a>
#### `SuperkollSalaryType`

Enum: `None`, `Simple`, `Deviations`, `WintSalary`
  
_Values_: 0 - None, 1 - Simple, 2 - Deviations, 3 - WintSalary

<a id="schema-supportattachment"></a>
#### `SupportAttachment`

Full attachment which contains meta data and data.

| Field | Type | Description |
|---|---|---|
| `Data`? | `string(byte)` | The attachment's data. |
| `Id` | `integer(int32)` | The identifier for the attachment. |
| `FileName`? | `string` | The file name of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |
| `FileSize`? | `integer(int64)` | File size of the attachement in bytes |

<a id="schema-supportattachmentsimple"></a>
#### `SupportAttachmentSimple`

Simplified attachment which only contains meta data of an attachment.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier for the attachment. |
| `FileName`? | `string` | The file name of the attachment. |
| `ContentType`? | `string` | The content type of the attachment. |
| `FileSize`? | `integer(int64)` | File size of the attachement in bytes |

<a id="schema-supportcategory"></a>
#### `SupportCategory`

A category for a support issue.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier of the support category. |
| `Name`? | `string` | The name of the support category. |

<a id="schema-supportcomment"></a>
#### `SupportComment`

Represents a comment posted to a support errand.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier of the comment. |
| `Created` | `string(date-time)` | The date and time in UTC the comment was made. |
| `User` | [`User`](#schema-user) |  |
| `FromWint` | `boolean` | If the user that posted the comment is from wint. |
| `FromAgency` | `boolean` | True if the comment's author is a member of the byrå the issue is stamped for (`SupportIssue.IsAgencyCase`). Always `false` on an unstamped issue. |
| `Attachments`? | [`SupportAttachmentSimple`](#schema-supportattachmentsimple)[] | Simplified attachments associated with the attachment. GET: /api/supportattachment/{id} |
| `HasRating` | `boolean` | If the comment already has been rated. |
| `Message`? | `string` | The comment message. |

<a id="schema-supportcommentpost"></a>
#### `SupportCommentPost`

Represents properties that can/must be set when posting a comment to a support errand.

| Field | Type | Description |
|---|---|---|
| `Attachments`? | [`SupportAttachment`](#schema-supportattachment)[] | Attachments associated with the comment. |
| `Message`? | `string` | The comment message. |

<a id="schema-supportcommentrating"></a>
#### `SupportCommentRating`

Represents a rating for a comment post in a support errand.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier of the comment rating. |
| `CreatedById`? | `integer(int32)` | The id of user that posted the rating. |
| `Created` | `string(date-time)` | The date and time in UTC the rating was made. |
| `Rating` | `number(float)` | The rating to be assigned to the support comment. |

<a id="schema-supportcommentratingpost"></a>
#### `SupportCommentRatingPost`

Represents properties that can/must be set when posting a rating for a support errand post.

| Field | Type | Description |
|---|---|---|
| `Rating` | `number(float)` | The rating to be assigned to the support comment. |

<a id="schema-supportissue"></a>
#### `SupportIssue`

Represents a support issue.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier for the support issue. |
| `User` | [`User`](#schema-user) |  |
| `Participants`? | [`User`](#schema-user)[] | The users who are participants of the support issue. |
| `FromWint` | `boolean` | If the user who created the support issue is from wint. |
| `Category` | [`SupportCategory`](#schema-supportcategory) |  |
| `CustomerMarkResolved` | `boolean` | True if support issue is marked as resolved by the customer |
| `Comments`? | [`SupportComment`](#schema-supportcomment)[] | Comments associated with the support issue. |
| `Attachments`? | [`SupportAttachmentSimple`](#schema-supportattachmentsimple)[] | Attachments associated with the support issue. |
| `Created` | `string(date-time)` | The date and time in UTC the issue was created. |
| `State` | [`SupportIssueState`](#schema-supportissuestate) |  |
| `StateChangedTimestamp` | `string(date-time)` | Timestamp in UTC when the state was changed. |
| `ImportanceOrder` | [`SupportIssueImportanceOrder`](#schema-supportissueimportanceorder) |  |
| `IsReadOnly` | `boolean` | True if the customer can't reply to the customer case |
| `IsUnread` | `boolean` | If the customer is unread by any participant |
| `IsUnreadByCurrentUser` | `boolean` | If the customer is unread by the current user |
| `IsConfidential` | `boolean` |  |
| `IsAgencyCase` | `boolean` |  |
| `IsOwnedByAgency` | `boolean` |  |
| `AgencyName`? | `string` |  |
| `IsLocked` | `boolean` |  |
| `CanRate` | `boolean` |  |
| `CanForward` | `boolean` |  |
| `IsViewerAgencyMember` | `boolean` |  |
| `Title`? | `string` | The title of the issue. |
| `Message`? | `string` | The message associated with the issue. |
| `CategoryId`? | `integer(int32)` | The identifier of the category to mark this issue with. |
| `Severity` | [`SupportIssueSeverity`](#schema-supportissueseverity) |  |
| `Recipient` | [`SupportIssueRecipient`](#schema-supportissuerecipient) |  |
| `PersonIds`? | `integer(int32)`[] | The ids of the customer persons the issue should be addressed to, when Wint.Superkoll.API.Model.SupportIssuePost.Recipient is Wint.Superkoll.API.Model.SupportIssueRecipient.Customer. Ignored otherwise. Must contain at least one id when used — a byrå cannot address a case to itself. |

<a id="schema-supportissueimportanceorder"></a>
#### `SupportIssueImportanceOrder`

Enum: `AtCustomer`, `AtSupport`, `Closed`

<a id="schema-supportissuelistitem"></a>
#### `SupportIssueListItem`

Light-weight version of the support issue.

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The identifier for the support issue. |
| `User` | [`User`](#schema-user) |  |
| `Participants`? | [`User`](#schema-user)[] | The users who are participants of the support issue. |
| `Title`? | `string` | The title of the issue. |
| `State` | [`SupportIssueState`](#schema-supportissuestate) |  |
| `LatestComment` | [`SupportComment`](#schema-supportcomment) |  |
| `StateChangedTimestamp` | `string(date-time)` | Timestamp in UTC when the state was changed. |
| `IsUnread` | `boolean` | Support issue is unread or read. |
| `ImportanceOrder` | [`SupportIssueImportanceOrder`](#schema-supportissueimportanceorder) |  |
| `IsConfidential` | `boolean` | True if the issue is confidential for an external agency, i.e. hidden from the agency's advisors. |
| `IsAgencyCase` | `boolean` | True if the issue is stamped for byråsupport, i.e. handled by an external agency rather than Wint directly. |
| `IsOwnedByAgency` | `boolean` | True if Wint.Superkoll.API.Model.SupportIssueListItem.IsAgencyCase is `true` and the issue is currently owned by a member of that agency — reassigning it to Wint leaves Wint.Superkoll.API.Model.SupportIssueListItem.IsAgencyCase set but makes this `false`. With Wint.Superkoll.API.Model.SupportIssueListItem.State, what the client derives its "Hos min byrå"/"Hos din byrå"/"Hos Wint" labels from. |
| `AgencyName`? | `string` | The name of the issue's agency when Wint.Superkoll.API.Model.SupportIssueListItem.IsAgencyCase is `true`; otherwise `null`. |
| `IsLocked` | `boolean` | True if the issue is a byrå case (Wint.Superkoll.API.Model.SupportIssueListItem.IsAgencyCase) locked because the byrå stopped being connected to the company — reassigned, unassigned, deactivated, or its assignment period expired. Nobody may reply, from the web app or by mail, until Wint takes it over. Narrower than Wint.Superkoll.API.Model.SupportIssue.IsReadOnly ("cannot be replied to, for any reason"): Wint's mass-created information issues are read-only from creation and are not locked. |
| `CanRate` | `boolean` | True if the issue can be rated by the customer. Always `false` for a byrå case (Wint.Superkoll.API.Model.SupportIssueListItem.IsAgencyCase) — rating is a Wint-support concept, not applicable when the byrå answers. |
| `CanForward` | `boolean` | True if the current viewer may forward this issue via `AgencyForward`: the issue is still owned by its byrå (Wint.Superkoll.API.Model.SupportIssueListItem.IsOwnedByAgency — not merely stamped, so a case Wint has taken over cannot be pulled back), it is not locked (Wint.Superkoll.API.Model.SupportIssueListItem.IsLocked), and the viewer is a member of that agency. Mirrors every condition `AgencyForward` itself enforces, so the action is never offered for a call that would be refused. |
| `IsViewerAgencyMember` | `boolean` | True if the viewer this response was projected for is a member of the issue's stamped agency — i.e. whether they see the issue from the byrå's side or the customer's. The client needs it to tell "Hos min byrå" from "Hos din byrå", which are otherwise the same tuple, and to hide the customer-side resolve buttons from a byrå member. Wint.Superkoll.API.Model.SupportIssueListItem.CanForward is not a substitute: it is false on a locked issue and false once Wint owns the issue, where the two labels would then collapse into one. |

<a id="schema-supportissuepost"></a>
#### `SupportIssuePost`

Properties for creating a support errand.

| Field | Type | Description |
|---|---|---|
| `Title`? | `string` | The title of the issue. |
| `Message`? | `string` | The message associated with the issue. |
| `CategoryId`? | `integer(int32)` | The identifier of the category to mark this issue with. |
| `Severity` | [`SupportIssueSeverity`](#schema-supportissueseverity) |  |
| `Attachments`? | [`SupportAttachment`](#schema-supportattachment)[] | Attachments associated with the issue. |
| `Recipient` | [`SupportIssueRecipient`](#schema-supportissuerecipient) |  |
| `PersonIds`? | `integer(int32)`[] | The ids of the customer persons the issue should be addressed to, when Wint.Superkoll.API.Model.SupportIssuePost.Recipient is Wint.Superkoll.API.Model.SupportIssueRecipient.Customer. Ignored otherwise. Must contain at least one id when used — a byrå cannot address a case to itself. |

<a id="schema-supportissuerecipient"></a>
#### `SupportIssueRecipient`

Enum: `Agency`, `Wint`, `Customer`

<a id="schema-supportissueseverity"></a>
#### `SupportIssueSeverity`

Enum: `Important`, `CanWait`, `NothingImportant`

<a id="schema-supportissuestate"></a>
#### `SupportIssueState`

Enum: `AtSupport`, `AtCustomer`, `Closed`

<a id="schema-supportsuggestedpersonscollection"></a>
#### `SupportSuggestedPersonsCollection`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-searchresult)[] | List of all booking tree items |

<a id="schema-surveys-answermodel"></a>
#### `Surveys.AnswerModel`

Describes an answer input.

| Field | Type | Description |
|---|---|---|
| `QuestionId` | `string(uuid)` | Gets or sets the `ID` of the question to which this answer relates. |
| `Kind` | [`QuestionsAndAnswers.AnswerKind`](#schema-questionsandanswers-answerkind) |  |
| `BooleanValue`? | `boolean` | Gets the System.Boolean answer value. |
| `FileValue`? | [`QuestionsAndAnswers.FileAnswerFileModel`](#schema-questionsandanswers-fileanswerfilemodel)[] | Gets the answer described as a sequence of Wint.Superkoll.API.Model.QuestionsAndAnswers.FileAnswerFileModel items. |
| `MatrixValue`? | [`QuestionsAndAnswers.MatrixValueModel`](#schema-questionsandanswers-matrixvaluemodel)[] | Gets the sequence of Wint.Superkoll.API.Model.QuestionsAndAnswers.MatrixValueModel values. |
| `SelectionValue`? | `integer(int32)`[] | Gets the sequence of selection values. |
| `StringSelectionValue`? | `string`[] | Value if the type is selection |
| `NumericValue`? | `integer(int32)` | Gets the System.Int32 answer value. |
| `TextValue`? | `string` | Gets the System.String answer value. |

<a id="schema-surveys-groupanswermodel"></a>
#### `Surveys.GroupAnswerModel`

Describes a group answer.

| Field | Type | Description |
|---|---|---|
| `QuestionGroupId` | `string(uuid)` | Gets the `ID` of the question group to which this group answer relates. |
| `IsEnabled` | `boolean` | Gets a value indicating if the question group is enabled. |

<a id="schema-surveys-questiongroupmodel"></a>
#### `Surveys.QuestionGroupModel`

Describes a question group.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Gets the `Id` of the question group. |
| `IsOptional` | `boolean` | Gets or sets a value indicating if the questions in this group are optional. |
| `IsHidden` | `boolean` | Gets or sets a value indicating if the questions in this group are hidden. |
| `Level`? | `string` | Gets the string representation of the level. |
| `Questions`? | [`Surveys.QuestionModel`](#schema-surveys-questionmodel)[] | Gets the sequence of Wint.Superkoll.API.Model.Surveys.QuestionModel items connected to this group. |
| `Name`? | `string` | Gets the name. |
| `Description`? | `string` | Gets the description. |

<a id="schema-surveys-questionmodel"></a>
#### `Surveys.QuestionModel`

Describes a question.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Gets the `Id` of the question. |
| `ParentId`? | `string(uuid)` | Gets the linked `ParentId` of the question. |
| `HiddenWhenParentSelectsYes` | `boolean` | Gets or sets the value based on the answer selected for the parent question. |
| `IsRequired` | `boolean` | Gets or sets a value indicating if an answer to this question is required. |
| `IsHidden` | `boolean` | Gets or sets a value indicating if the question is hidden. |
| `AnswerKind` | [`QuestionsAndAnswers.AnswerKind`](#schema-questionsandanswers-answerkind) |  |
| `Links`? | [`QuestionsAndAnswers.LinkModel`](#schema-questionsandanswers-linkmodel)[] | Gets the sequence of Wint.Superkoll.API.Model.QuestionsAndAnswers.LinkModel items connected to this question. |
| `MatrixDefinition` | [`QuestionsAndAnswers.QuestionMatrixDefinitionModel`](#schema-questionsandanswers-questionmatrixdefinitionmodel) |  |
| `SelectionDefinition` | [`QuestionsAndAnswers.QuestionSelectionDefinitionModel`](#schema-questionsandanswers-questionselectiondefinitionmodel) |  |
| `FileDefinition` | [`QuestionsAndAnswers.QuestionFileDefinitionModel`](#schema-questionsandanswers-questionfiledefinitionmodel) |  |
| `Ordinal` | `integer(int32)` | Gets the ordinal of the question in the survey. |
| `Body`? | `string` | Gets the question body. |
| `Description`? | `string` | Gets the question description. |
| `StringSelectionDefinition` | [`QuestionsAndAnswers.QuestionStringSelectionDefinitionModel`](#schema-questionsandanswers-questionstringselectiondefinitionmodel) |  |

<a id="schema-surveys-survey"></a>
#### `Surveys.Survey`

Represents a survey. Used by customer.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Gets the `Id` identifying this survey. |
| `SurveyResponse` | [`Surveys.SurveyResponseOutputModel`](#schema-surveys-surveyresponseoutputmodel) |  |
| `SurveyTemplate` | [`Surveys.SurveyTemplateModel`](#schema-surveys-surveytemplatemodel) |  |
| `Comments`? | [`Surveys.SurveyComment`](#schema-surveys-surveycomment)[] | Gets or sets the survey comments |

<a id="schema-surveys-surveyattachment"></a>
#### `Surveys.SurveyAttachment`

| Field | Type | Description |
|---|---|---|
| `ContentType`? | `string` | Attachment content type e.g. application/pdf, image/png, ... |
| `Data`? | `string(byte)` | Attachment data |
| `FileName`? | `string` | The name of the attachment. |

<a id="schema-surveys-surveycomment"></a>
#### `Surveys.SurveyComment`

Describes a survey comment

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Gets or sets id |
| `CreatedById`? | `integer(int32)` | Gets or sets created by id |
| `CreatedByName`? | `string` | Gets or sets created by name |
| `Created` | `string(date-time)` | Gets or sets the date and time this survey comment was created. |
| `Message`? | `string` | Gets or sets the message |

<a id="schema-surveys-surveycommentrequest"></a>
#### `Surveys.SurveyCommentRequest`

Describes a survey comment request

| Field | Type | Description |
|---|---|---|
| `Message`? | `string` | Gets or sets the message |

<a id="schema-surveys-surveypersonssuggestioncollection"></a>
#### `Surveys.SurveyPersonsSuggestionCollection`

Survey person suggestion response

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-searchresult)[] | List of all suggestions |

<a id="schema-surveys-surveyresponseinputmodel"></a>
#### `Surveys.SurveyResponseInputModel`

Describes a survey response input model.

| Field | Type | Description |
|---|---|---|
| `IsFinal` | `boolean` | Gets a value indicating if this response is final. |
| `SurveyId` | `string(uuid)` | Gets the `Id` of the survey this response is connected to. |
| `Answers`? | [`Surveys.AnswerModel`](#schema-surveys-answermodel)[] | Gets the sequence of answers in this survey response. |
| `GroupAnswers`? | [`Surveys.GroupAnswerModel`](#schema-surveys-groupanswermodel)[] | Gets the sequence of group answers in this survey response. |

<a id="schema-surveys-surveyresponseoutputmodel"></a>
#### `Surveys.SurveyResponseOutputModel`

Describes a survey response output model.

| Field | Type | Description |
|---|---|---|
| `IsFinal` | `boolean` | Gets a value indicating if this response is final. |
| `SurveyId` | `string(uuid)` | Gets the `Id` of the survey this response is connected to. |
| `Answers`? | [`Surveys.AnswerModel`](#schema-surveys-answermodel)[] | Gets the sequence of answers in this survey response. |
| `GroupAnswers`? | [`Surveys.GroupAnswerModel`](#schema-surveys-groupanswermodel)[] | Gets the sequence of group answers in this survey response. |
| `Created` | `string(date-time)` | Gets the date and time the survey response was created. |
| `Updated` | `string(date-time)` | Gets the date and time the survey response was updated. |

<a id="schema-surveys-surveysendtopersonaction"></a>
#### `Surveys.SurveySendToPersonAction`

Model for assigning survey to another person

| Field | Type | Description |
|---|---|---|
| `PersonId` | `integer(int32)` | Id of the person to send the survey to |

<a id="schema-surveys-surveystatus"></a>
#### `Surveys.SurveyStatus`

Describes the status of a survey.

| Field | Type | Description |
|---|---|---|
| `SurveyId` | `string(uuid)` | Gets the `Id` of the survey. |
| `Description`? | `string` | Gets the description of the survey. |
| `NumberOfQuestionsLeftToAnswer` | `integer(int32)` | Gets the total number of questions in the survey that has not been answered. |
| `LastUpdated`? | `string(date-time)` | Gets the date and time the survey response was updated. |
| `LastDateToAnswer` | `string(date-time)` | Gets the date and time to when the survey request is valid. |
| `FromDate` | `string(date-time)` | Gets the date and time from when the survey request is valid. |
| `Comments`? | [`Surveys.SurveyComment`](#schema-surveys-surveycomment)[] | Gets or sets the survey comments |

<a id="schema-surveys-surveytemplatemodel"></a>
#### `Surveys.SurveyTemplateModel`

Describes a survey ouput model.

| Field | Type | Description |
|---|---|---|
| `Created` | `string(date-time)` | Gets the date and time the survey was created. |
| `ExternalId` | `string(uuid)` | Gets the external `Id` of the survey. |
| `Name`? | `string` | Gets the name of the survey. |
| `QuestionGroups`? | [`Surveys.QuestionGroupModel`](#schema-surveys-questiongroupmodel)[] | Gets the sequence of question groups in the survey. |

<a id="schema-taxtableinfo"></a>
#### `TaxTableInfo`

Enum: `None`, `TaxTable29`, `TaxTable30`, `TaxTable31`, `TaxTable32`, `TaxTable33`, `TaxTable34`, `TaxTable35`, `TaxTable36`, `TaxTable37`, `TaxTable38`, `TaxTable39`, `TaxTable40`, `TaxTable41`, `TaxTable42`
  
_Values_: 0 - None, 29 - TaxTable29, 30 - TaxTable30, 31 - TaxTable31, 32 - TaxTable32, 33 - TaxTable33, 34 - TaxTable34, 35 - TaxTable35, 36 - TaxTable36, 37 - TaxTable37, 38 - TaxTable38, 39 - TaxTable39, 40 - TaxTable40, 41 - TaxTable41, 42 - TaxTable42

<a id="schema-timereporting-invoicecreditingstate"></a>
#### `TimeReporting.InvoiceCreditingState`

Enum: `NotCredited`, `PartiallyCredited`, `FullyCredited`

<a id="schema-timereporting-timereportinvoiceinfo"></a>
#### `TimeReporting.TimeReportInvoiceInfo`

Details of invoice connected to project time

| Field | Type | Description |
|---|---|---|
| `SerialNumber` | `integer(int32)` | Serial number of invoice |
| `InvoiceId` | `integer(int32)` | Invoice id of invoice |
| `InvoiceDate` | `string(date-time)` | Invoice date of invoice |
| `Amount` | `number(double)` | Amount of invoice |
| `Currency`? | `string` | Currency of invoice |
| `CustomerName`? | `string` | Customer name of invoice |
| `InvoiceState` | [`InvoiceStatus`](#schema-invoicestatus) |  |
| `CreditingState` | [`TimeReporting.InvoiceCreditingState`](#schema-timereporting-invoicecreditingstate) |  |

<a id="schema-timereporting-timereportinvoicestatus"></a>
#### `TimeReporting.TimeReportInvoiceStatus`

Enum: `Unhandled`, `Draft`, `Sent`, `Credited`, `PartlyCredited`, `PartlyConnectedToInvoices`, `AllConnectedToInvoices`

<a id="schema-timereporting-timereportstatus"></a>
#### `TimeReporting.TimeReportStatus`

Enum: `Open`, `Locked`, `Approved`, `Attested`

<a id="schema-timereporting-timereportingexportrow"></a>
#### `TimeReporting.TimeReportingExportRow`

Export row

| Field | Type | Description |
|---|---|---|
| `PersonId` | `integer(int32)` | Person Id |
| `Person`? | `string` | Person |
| `Date` | `string(date-time)` | Time report date |
| `Project`? | `string` | Project name |
| `Currency`? | `string` | Currency |
| `CategoryId` | `integer(int32)` | Category Id |
| `Category`? | `string` | Category name |
| `Hours` | `number(double)` | Hours |
| `Rate` | `number(double)` | Rate |
| `ExternalComment`? | `string` | External comment |
| `InternalComment`? | `string` | Internal comment |

<a id="schema-timereporting-timereportingpersonprojectbillingmodel"></a>
#### `TimeReporting.TimeReportingPersonProjectBillingModel`

Enum: `Hourly`, `FixedPrice`, `FixedPriceMinusDeviations`

<a id="schema-timereporting-timereportingreportcolumn"></a>
#### `TimeReporting.TimeReportingReportColumn`

| Field | Type | Description |
|---|---|---|
| `TimeReportingProjectId`? | `string(uuid)` | Project id for the time reporting project |
| `ProjectTimeId`? | `integer(int32)` | ProjectTimeId |
| `FromDate` | `string(date-time)` | Date that current record is valid from |
| `ToDate`? | `string(date-time)` | Date that current record is valid to |
| `ProjectTime`? | `number(double)` | Reported hours project time |
| `InternalProjectTime`? | `number(double)` | Reported hours internal project time |
| `HourlyRate`? | `number(double)` | Hourly Rate |
| `HoursToInvoice`? | `number(double)` | Number of hours to invoice |
| `CalculatedAmount`? | `number(double)` | Calculated amount (including already billed amount) |
| `InvoicedAmount`? | `number(double)` | Billed amount |
| `CurrencyCode`? | `string` | Currency code |
| `Absence`? | `number(double)` | Absence |
| `InvoiceId`? | `integer(int32)` | The invoice id that contains the record |
| `InvoiceSerialNumber`? | `integer(int32)` | Serial number on invoice or draft |
| `TimeReportInvoiceStatus` | [`TimeReporting.TimeReportInvoiceStatus`](#schema-timereporting-timereportinvoicestatus) |  |
| `BillingModel` | [`TimeReporting.TimeReportingPersonProjectBillingModel`](#schema-timereporting-timereportingpersonprojectbillingmodel) |  |
| `Allowance`? | `number(double)` | Column for all types of allowances. Could be in hours or currency |
| `DeviationType` | [`SalaryDeviationType`](#schema-salarydeviationtype) |  |
| `TimeReportStatus` | [`TimeReporting.TimeReportStatus`](#schema-timereporting-timereportstatus) |  |
| `ApprovedBy`? | `string` | Who soft approved the time report (if approved) |
| `UtilizationRate`? | `number(double)` | Efficiency (project time / total time) |
| `AmountToInvoice`? | `number(double)` | Amount to invoice |
| `CategoryId` | `integer(int32)` | Category Id |
| `CategoryName`? | `string` | Category Name |
| `CommentsCount` | `integer(int32)` | Number of comments |
| `Invoices`? | [`TimeReporting.TimeReportInvoiceInfo`](#schema-timereporting-timereportinvoiceinfo)[] | List of invoices connected |

<a id="schema-timereporting-timereportingreportrow"></a>
#### `TimeReporting.TimeReportingReportRow`

A row in time reporting report

| Field | Type | Description |
|---|---|---|
| `PersonId` | `integer(int32)` | Project member id |
| `Description`? | `string` | Row header |
| `TimeReportingReportRowLevel` | [`TimeReporting.TimeReportingReportRowLevel`](#schema-timereporting-timereportingreportrowlevel) |  |
| `TimeReportingReportRowType` | [`TimeReporting.TimeReportingReportRowType`](#schema-timereporting-timereportingreportrowtype) |  |
| `Columns`? | [`TimeReporting.TimeReportingReportColumn`](#schema-timereporting-timereportingreportcolumn)[] | Columns |
| `Children`? | [`TimeReporting.TimeReportingReportRow`](#schema-timereporting-timereportingreportrow)[] | Children |

<a id="schema-timereporting-timereportingreportrowlevel"></a>
#### `TimeReporting.TimeReportingReportRowLevel`

Enum: `Level1PersonSummary`, `Level2SubTotal`, `Level3DetailsOrCategorySummary`, `Level4TimeReports`

<a id="schema-timereporting-timereportingreportrowtype"></a>
#### `TimeReporting.TimeReportingReportRowType`

Enum: `PersonSummary`, `ProjectSummary`, `DeviationSummary`, `AllowanceSummary`, `ProjectDetails`, `InternalTimeDetails`, `Vacation`, `CareOfChildren`, `Abscence`, `ParentalLeave`, `TenDays`, `LeaveOfAbsence`, `Mileage`, `CommissionFee`, `AllowanceDomestic`, `AllowanceForeign`, `WorkedHours`, `WithdrawalCompensation`, `DepositedCompensation`, `Other`, `CommissionVacationPaid`, `CommissionVacationSaved`, `WithdrawalsSavedVacation`, `Bonus`, `CustomTimeDeviation`, `CustomDeviationCompensation`, `ProjectCategorySummary`, `Overtime50`, `Overtime75`, `Overtime100`, `Overtime150`, `Overtime200`, `OvertimeSimple`, `OvertimeQualified`, `ExtraTime`, `UnsocialWorkingHours1`, `UnsocialWorkingHours2`, `UnsocialWorkingHours3`, `UnsocialWorkingHours4`, `OnCall`, `Preparedness`, `Overtime30`, `TravelTimeSimple`, `TravelTimeQualified`, `ReducedWorkingHours`

<a id="schema-timereportinginterval"></a>
#### `TimeReportingInterval`

Enum: `Weekly`, `Monthly`
  
_Values_: 0 - Weekly, 1 - Monthly

<a id="schema-timereportingsettings"></a>
#### `TimeReportingSettings`

| Field | Type | Description |
|---|---|---|
| `IsTimeReportingMandatory` | `boolean` |  |
| `TimeReportingInterval` | [`TimeReportingInterval`](#schema-timereportinginterval) |  |

<a id="schema-unit"></a>
#### `Unit`

| Field | Type | Description |
|---|---|---|
| `Id` | `integer(int32)` | The id of the unit which will be returned when creating a Unit |
| `Name` | `string` | The name of the unit |

<a id="schema-unitofdeviationvalue"></a>
#### `UnitOfDeviationValue`

Enum: `Km`, `SEK`, `Days`, `Hours`
  
_Values_: 0 - Km, 1 - SEK, 2 - Days, 3 - Hours

<a id="schema-unitpost"></a>
#### `UnitPost`

| Field | Type | Description |
|---|---|---|
| `Name` | `string` | The name of the unit |

<a id="schema-user"></a>
#### `User`

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` |  |
| `Id` | `integer(int32)` |  |

<a id="schema-userlogininfo"></a>
#### `UserLoginInfo`

| Field | Type | Description |
|---|---|---|
| `Key` | `string(uuid)` |  |
| `Name`? | `string` |  |
| `PersonId` | `integer(int32)` |  |
| `PersonNumber`? | `string` |  |
| `ReceiptBankAccount`? | `string` |  |
| `ReceiptBankAccountClearing`? | `string` |  |
| `Mail`? | `string` |  |
| `State` | [`LoginState`](#schema-loginstate) |  |
| `CompanyNames`? | `string`[] |  |
| `PaymentMethods`? | [`ReceiptPaymentMethod`](#schema-receiptpaymentmethod)[] |  |
| `AuthTokens` | [`AuthTokens`](#schema-authtokens) |  |
| `IsHeartUser` | `boolean` |  |
| `ShownIntroductions`? | `string`[] |  |
| `ShownHelps`? | `string`[] |  |
| `HasMissingPaymentDetails` | `boolean` |  |
| `UnsignedEula` | `boolean` |  |
| `CanSuspendEula` | `boolean` |  |

<a id="schema-vatreportactionreason"></a>
#### `VatReportActionReason`

Enum: `None`, `UploadFailed`, `Rejected`, `AuthorizationFailure`, `MissingPeriod`, `StoppedByValidation`

<a id="schema-vatreportbox"></a>
#### `VatReportBox`

| Field | Type | Description |
|---|---|---|
| `Code`? | `string` | Skatteverket's box number, e.g. "05" or "49". |
| `Description`? | `string` |  |
| `Amount` | `number(double)` |  |

<a id="schema-vatreportdetails"></a>
#### `VatReportDetails`

| Field | Type | Description |
|---|---|---|
| `Boxes`? | [`VatReportBox`](#schema-vatreportbox)[] | Every box of the declaration in the order of Skatteverket's form: A, B, C, D, H, I, E, F, G. |
| `AdditionalInformation`? | `string` | The report's free-text "Övriga upplysningar". |
| `VoucherNumber`? | `string` | Series and number of the booking voucher, e.g. "V1042"; null when not booked. |
| `Id` | `string(uuid)` |  |
| `Start` | `string(date-time)` |  |
| `End` | `string(date-time)` | Last day of the period, inclusive. |
| `IsCorrection` | `boolean` |  |
| `Status` | [`VatReportStatus`](#schema-vatreportstatus) |  |
| `ActionReason` | [`VatReportActionReason`](#schema-vatreportactionreason) |  |
| `FiledByCustomer` | `boolean` | The customer files this declaration with Skatteverket, not Wint: a booked report Wint sent no declaration for, or a draft of a company whose declarations Wint does not file. |
| `DueDate`? | `string(date-time)` |  |
| `IsOverdue` | `boolean` | The payment Wint handles can no longer reach Skatteverket in time and no tax invoice pays it yet, by the rule behind Heart's overdue banner. Only ever true for the company's latest booked report. |
| `AmountToPay`? | `number(double)` | Box 49: positive to pay, negative to get back. Null when the report could not be read. |

<a id="schema-vatreportstatus"></a>
#### `VatReportStatus`

Enum: `Draft`, `Booked`, `AwaitingSignature`, `Submitted`, `ActionRequired`, `BeingRemoved`

<a id="schema-vatreportsummary"></a>
#### `VatReportSummary`

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` |  |
| `Start` | `string(date-time)` |  |
| `End` | `string(date-time)` | Last day of the period, inclusive. |
| `IsCorrection` | `boolean` |  |
| `Status` | [`VatReportStatus`](#schema-vatreportstatus) |  |
| `ActionReason` | [`VatReportActionReason`](#schema-vatreportactionreason) |  |
| `FiledByCustomer` | `boolean` | The customer files this declaration with Skatteverket, not Wint: a booked report Wint sent no declaration for, or a draft of a company whose declarations Wint does not file. |
| `DueDate`? | `string(date-time)` |  |
| `IsOverdue` | `boolean` | The payment Wint handles can no longer reach Skatteverket in time and no tax invoice pays it yet, by the rule behind Heart's overdue banner. Only ever true for the company's latest booked report. |
| `AmountToPay`? | `number(double)` | Box 49: positive to pay, negative to get back. Null when the report could not be read. |

<a id="schema-vatreportsavailability"></a>
#### `VatReportsAvailability`

| Field | Type | Description |
|---|---|---|
| `Available` | `boolean` | The company has an external agency selected in Heart and keeps its books in Wint Accounting, so the advisor's VAT reports are shown. |

<a id="schema-warning"></a>
#### `Warning`

Issues that need attention

| Field | Type | Description |
|---|---|---|
| `Message`? | `string` | The warning message |
| `Type` | [`WarningType`](#schema-warningtype) |  |
| `Level` | [`WarningLevel`](#schema-warninglevel) |  |
| `Category` | [`WarningCategory`](#schema-warningcategory) |  |

<a id="schema-warningcategory"></a>
#### `WarningCategory`

Enum: `EUVATWarnings`, `AutogiroWarnings`, `AutogiroWarningsWithReceipt`, `AutogiroPaymentHandling`, `OldInvoice`, `Printing`, `EInvoicing`, `ForwardedCosts`, `NotDefined`
  
_Values_: 1 - EUVATWarnings, 2 - AutogiroWarnings, 3 - AutogiroWarningsWithReceipt, 4 - AutogiroPaymentHandling, 5 - OldInvoice, 6 - Printing, 7 - EInvoicing, 8 - ForwardedCosts, -1 - NotDefined

<a id="schema-warninglevel"></a>
#### `WarningLevel`

Enum: `NotDefined`, `Error`, `Warning`, `Info`, `Success`
  
_Values_: 0 - NotDefined, 1 - Error, 2 - Warning, 3 - Info, 4 - Success

<a id="schema-warningtype"></a>
#### `WarningType`

Enum: `EuCustomerWithNoVatNumberDisplay`, `EuCustomerWithInvalidVatNumberForDeliveryAddress`, `EuCustomerWithInvalidVatNumberForBillingAddress`, `UncategorizedEuCustomerInvoiceItems`, `EuCustomerInvoiceWithApplicableItemsButNoVatNumber`, `EuCustomerInvoiceWithInvalidVatNumberForItemCategory`, `EuCustomerInvoiceItemsWithCategoryUnknown`, `AutogiroHandledByWint`, `AutogiroNotHandledByWint`, `AutogiroHandleByWintWithReceiptManualSend`, `AutogiroHandleByWintWithReceiptAutomaticSend`, `AutogiroNotHandleByWintWithReceiptManualSend`, `AutogiroNotHandleByWintWithReceiptAutomaticSend`, `AutogiroPaymentHandledByWint`, `AutogiroPaymentNotHandledByWint`, `CannotSendOldInvoice`, `SendForPrint`, `MissingCustomerReferenceCode`, `MissingCustomerElectronicIdentifiers`, `SendAsEInvoice`, `ForwardedCostSourceDocumentCancelled`, `WarningTypeNotDefined`

<a id="schema-wint-support-service-model-agent-agentcardrow"></a>
#### `Wint.Support.Service.Model.Agent.AgentCardRow`

| Field | Type | Description |
|---|---|---|
| `Label`? | `string` |  |
| `Value`? | `string` |  |

<a id="schema-wint-support-service-model-agent-agentcasecreated"></a>
#### `Wint.Support.Service.Model.Agent.AgentCaseCreated`

| Field | Type | Description |
|---|---|---|
| `CaseId` | `integer(int32)` |  |
| `AssignedTo`? | `string` |  |

<a id="schema-wint-support-service-model-agent-agentcaserequest"></a>
#### `Wint.Support.Service.Model.Agent.AgentCaseRequest`

| Field | Type | Description |
|---|---|---|
| `Category`? | `string` |  |
| `Subject`? | `string` |  |
| `CustomerText`? | `string` |  |
| `Understood`? | [`Wint.Support.Service.Model.Agent.AgentCardRow`](#schema-wint-support-service-model-agent-agentcardrow)[] |  |
| `Tried`? | `string` |  |
| `Urgent`? | `boolean` |  |
| `Summary`? | `string` |  |
| `Conversation`? | [`Wint.Support.Service.Model.Agent.AgentConversationLine`](#schema-wint-support-service-model-agent-agentconversationline)[] |  |

<a id="schema-wint-support-service-model-agent-agentcasesummary"></a>
#### `Wint.Support.Service.Model.Agent.AgentCaseSummary`

| Field | Type | Description |
|---|---|---|
| `Subject`? | `string` |  |
| `Summary`? | `string` |  |
| `Category`? | `string` |  |
| `Drafted` | `boolean` |  |
| `Found`? | [`Wint.Support.Service.Model.Agent.AgentCardRow`](#schema-wint-support-service-model-agent-agentcardrow)[] |  |
| `References`? | `string`[] |  |
| `Reason`? | `string` |  |

<a id="schema-wint-support-service-model-agent-agentcasesummaryrequest"></a>
#### `Wint.Support.Service.Model.Agent.AgentCaseSummaryRequest`

| Field | Type | Description |
|---|---|---|
| `Conversation`? | [`Wint.Support.Service.Model.Agent.AgentConversationLine`](#schema-wint-support-service-model-agent-agentconversationline)[] |  |
| `Language`? | `string` |  |

<a id="schema-wint-support-service-model-agent-agentconversationline"></a>
#### `Wint.Support.Service.Model.Agent.AgentConversationLine`

| Field | Type | Description |
|---|---|---|
| `Who`? | `string` |  |
| `Text`? | `string` |  |

<a id="schema-wint-support-service-model-agent-agentmessagerequest"></a>
#### `Wint.Support.Service.Model.Agent.AgentMessageRequest`

| Field | Type | Description |
|---|---|---|
| `Text`? | `string` |  |

<a id="schema-wint-support-service-model-agent-agentreply"></a>
#### `Wint.Support.Service.Model.Agent.AgentReply`

Type: `object`

<a id="schema-wint-support-service-model-agent-agentsessioncreated"></a>
#### `Wint.Support.Service.Model.Agent.AgentSessionCreated`

| Field | Type | Description |
|---|---|---|
| `SessionId` | `string(uuid)` |  |

<a id="schema-wint-utils-webapi-listresponseof-accounting-account"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Accounting.Account`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Accounting.Account`](#schema-accounting-account)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Accounting.Account`](#schema-accounting-account) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-accounting-series"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Accounting.Series`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Accounting.Series`](#schema-accounting-series)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Accounting.Series`](#schema-accounting-series) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-accounting-transaction"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Accounting.Transaction`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Accounting.Transaction`](#schema-accounting-transaction)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Accounting.Transaction`](#schema-accounting-transaction) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-accounting-voucher"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Accounting.Voucher`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Accounting.Voucher`](#schema-accounting-voucher)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Accounting.Voucher`](#schema-accounting-voucher) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-article"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Article`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Article`](#schema-article)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Article`](#schema-article) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-cashreconciliationinstancedescriptor"></a>
#### `Wint.Utils.WebApi.ListResponseOf_CashReconciliationInstanceDescriptor`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`CashReconciliationInstanceDescriptor`](#schema-cashreconciliationinstancedescriptor)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`CashReconciliationInstanceDescriptor`](#schema-cashreconciliationinstancedescriptor) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-customer"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Customer`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Customer`](#schema-customer)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Customer`](#schema-customer) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-dimension"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Dimension`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Dimension`](#schema-dimension)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Dimension`](#schema-dimension) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-dimensiontype"></a>
#### `Wint.Utils.WebApi.ListResponseOf_DimensionType`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`DimensionType`](#schema-dimensiontype)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`DimensionType`](#schema-dimensiontype) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-employee"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Employee`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Employee`](#schema-employee)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Employee`](#schema-employee) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-invoice"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Invoice`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Invoice`](#schema-invoice)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Invoice`](#schema-invoice) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-invoicelistitem"></a>
#### `Wint.Utils.WebApi.ListResponseOf_InvoiceListItem`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`InvoiceListItem`](#schema-invoicelistitem)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`InvoiceListItem`](#schema-invoicelistitem) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-invoicepaymentoption"></a>
#### `Wint.Utils.WebApi.ListResponseOf_InvoicePaymentOption`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`InvoicePaymentOption`](#schema-invoicepaymentoption)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`InvoicePaymentOption`](#schema-invoicepaymentoption) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-monthlyreportsummary"></a>
#### `Wint.Utils.WebApi.ListResponseOf_MonthlyReportSummary`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`MonthlyReportSummary`](#schema-monthlyreportsummary)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`MonthlyReportSummary`](#schema-monthlyreportsummary) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-personmonthlysalarydeviation"></a>
#### `Wint.Utils.WebApi.ListResponseOf_PersonMonthlySalaryDeviation`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`PersonMonthlySalaryDeviation`](#schema-personmonthlysalarydeviation)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`PersonMonthlySalaryDeviation`](#schema-personmonthlysalarydeviation) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-receipt"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Receipt`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Receipt`](#schema-receipt)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Receipt`](#schema-receipt) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-reference"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Reference`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Reference`](#schema-reference)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Reference`](#schema-reference) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-revenuereportdescriptor"></a>
#### `Wint.Utils.WebApi.ListResponseOf_RevenueReportDescriptor`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`RevenueReportDescriptor`](#schema-revenuereportdescriptor)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`RevenueReportDescriptor`](#schema-revenuereportdescriptor) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-rutrotworktype"></a>
#### `Wint.Utils.WebApi.ListResponseOf_RutRotWorkType`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`RutRotWorkType`](#schema-rutrotworktype)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`RutRotWorkType`](#schema-rutrotworktype) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-salarydeviationdescriptor"></a>
#### `Wint.Utils.WebApi.ListResponseOf_SalaryDeviationDescriptor`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`SalaryDeviationDescriptor`](#schema-salarydeviationdescriptor)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`SalaryDeviationDescriptor`](#schema-salarydeviationdescriptor) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-salarydeviationmonth"></a>
#### `Wint.Utils.WebApi.ListResponseOf_SalaryDeviationMonth`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`SalaryDeviationMonth`](#schema-salarydeviationmonth)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`SalaryDeviationMonth`](#schema-salarydeviationmonth) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-salarydraft"></a>
#### `Wint.Utils.WebApi.ListResponseOf_SalaryDraft`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`SalaryDraft`](#schema-salarydraft)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`SalaryDraft`](#schema-salarydraft) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-searchcustomerinformationresponse"></a>
#### `Wint.Utils.WebApi.ListResponseOf_SearchCustomerInformationResponse`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`SearchCustomerInformationResponse`](#schema-searchcustomerinformationresponse)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`SearchCustomerInformationResponse`](#schema-searchcustomerinformationresponse) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-supportcomment"></a>
#### `Wint.Utils.WebApi.ListResponseOf_SupportComment`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`SupportComment`](#schema-supportcomment)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`SupportComment`](#schema-supportcomment) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-supportissue"></a>
#### `Wint.Utils.WebApi.ListResponseOf_SupportIssue`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`SupportIssue`](#schema-supportissue)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`SupportIssue`](#schema-supportissue) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-supportissuelistitem"></a>
#### `Wint.Utils.WebApi.ListResponseOf_SupportIssueListItem`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`SupportIssueListItem`](#schema-supportissuelistitem)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`SupportIssueListItem`](#schema-supportissuelistitem) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-unit"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Unit`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Unit`](#schema-unit)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Unit`](#schema-unit) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-vatreportsummary"></a>
#### `Wint.Utils.WebApi.ListResponseOf_VatReportSummary`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`VatReportSummary`](#schema-vatreportsummary)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`VatReportSummary`](#schema-vatreportsummary) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-listresponseof-wint-utils-webapi-searchresult"></a>
#### `Wint.Utils.WebApi.ListResponseOf_Wint.Utils.WebApi.SearchResult`

| Field | Type | Description |
|---|---|---|
| `Items`? | [`Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-searchresult)[] |  |
| `NumPerPage` | `integer(int32)` |  |
| `Page` | `integer(int32)` |  |
| `SummaryItem` | [`Wint.Utils.WebApi.SearchResult`](#schema-wint-utils-webapi-searchresult) |  |
| `TotalItems` | `integer(int32)` |  |
| `TotalItemsWithOutFilter` | `integer(int32)` |  |

<a id="schema-wint-utils-webapi-searchresult"></a>
#### `Wint.Utils.WebApi.SearchResult`

| Field | Type | Description |
|---|---|---|
| `Description`? | `string` |  |
| `Id`? | `string` |  |
| `Name`? | `string` |  |

<a id="schema-wintsalary-deviations-amountdescription"></a>
#### `WintSalary.Deviations.AmountDescription`

Represents an amount and description for salary deviations

| Field | Type | Description |
|---|---|---|
| `Amount` | `number(double)` | Amount specified |
| `Description`? | `string` | Description of the amount |

<a id="schema-wintsalary-deviations-child"></a>
#### `WintSalary.Deviations.Child`

A child associated with a person, used for parental leave deviation selection.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier of the child. |
| `Name`? | `string` | Name of the child. |
| `DateOfBirth` | `string(date-time)` | Date of birth of the child (or expected date of birth for unborn children). |
| `SoleCustody` | `boolean` | Whether the parent has sole custody of the child. |

<a id="schema-wintsalary-deviations-childforcreate"></a>
#### `WintSalary.Deviations.ChildForCreate`

DTO for creating a Child record associated with a person.

| Field | Type | Description |
|---|---|---|
| `Name` | `string` | Name of the child. |
| `DateOfBirth` | `string(date-time)` | Date of birth of the child (or expected date of birth for unborn children). |
| `SoleCustody` | `boolean` | Whether the parent has sole custody of the child. |

<a id="schema-wintsalary-deviations-currentmonthplacement"></a>
#### `WintSalary.Deviations.CurrentMonthPlacement`

Enum: `Never`, `Optional`, `Always`

<a id="schema-wintsalary-deviations-dayminutes"></a>
#### `WintSalary.Deviations.DayMinutes`

Represents a day and minutes entry in a salary deviations (Mostly in absence category).

| Field | Type | Description |
|---|---|---|
| `Day` | `string(date-time)` | Date where the minutes are registered. |
| `Minutes` | `integer(int32)` | Number of minutes registered for the day. |

<a id="schema-wintsalary-deviations-deviationperiodyearmonthstate"></a>
#### `WintSalary.Deviations.DeviationPeriodYearMonthState`

Represents the state of a salary deviation for a specific year-month period.

| Field | Type | Description |
|---|---|---|
| `YearMonth` | `integer(int32)` | Calendar month (YYYYMM) the period's dates fall in. Not the salary month it is paid in, which is usually the following month. |
| `State` | [`WintSalary.Deviations.SalaryDeviationState`](#schema-wintsalary-deviations-salarydeviationstate) |  |
| `IsYearMonthFinalized` | `boolean` | Whether the salary month this period is paid in is locked or already calculated; changes to such a period are restricted. |

<a id="schema-wintsalary-deviations-fuelbenefit"></a>
#### `WintSalary.Deviations.FuelBenefit`

Fuel benefit (drivmedelsförmån) inputs. The salary service calculates the deviation value from them.

| Field | Type | Description |
|---|---|---|
| `FuelCost` | `number(double)` | Employer-paid fuel cost for the month, at market value including VAT. Gross, before any employee repayment: repayments are reported separately. |
| `PrivateDistance` | `number(double)` | Private driving distance, in the same unit as Wint.Superkoll.API.Model.WintSalary.Deviations.FuelBenefit.BusinessDistance. |
| `BusinessDistance`? | `number(double)` | Business driving distance. Missing counts as zero, so all driving is private. |

<a id="schema-wintsalary-deviations-salarydeviation"></a>
#### `WintSalary.Deviations.SalaryDeviation`

Represents a salary deviation with detailed information.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier for the salary deviation. |
| `DeviationTypeId` | `string(uuid)` | Unique identifier for the salary deviation type. |
| `DeviationTypeName`? | `string` | Name of the salary deviation type. |
| `ReportedPersonName`? | `string` | Name of the person who own the salary deviation. |
| `ReportedPersonId` | `integer(int32)` | Unique identifier for the person who own the salary deviation. |
| `State` | [`WintSalary.Deviations.SalaryDeviationState`](#schema-wintsalary-deviations-salarydeviationstate) |  |
| `YearAndMonth`? | `integer(int32)` | Deprecated: echoes the `yearMonth` the request selected (YYYYMM), or null when it selected none. It does not describe the deviation itself; read Wint.Superkoll.API.Model.WintSalary.Deviations.SalaryDeviation.PeriodYearMonthStates instead. *(deprecated)* |
| `PeriodYearMonthStates`? | [`WintSalary.Deviations.DeviationPeriodYearMonthState`](#schema-wintsalary-deviations-deviationperiodyearmonthstate)[] | One entry per calendar month the deviation's dates fall in (a deviation is stored as one period per month), with that month's state. Always covers every month of the deviation, also when the request selected only some of them. Filled by the get-by-id endpoint only; empty in list and mutation responses. |
| `FullDeviationLoaded`? | `boolean` | False when the request selected only some of the deviation's months, in which case `FromDate`, `ToDate`, `Value`, `DayMinutes` and `State` describe those months only. |
| `UseCurrentMonthPlacement` | `boolean` | Whether this deviation is placed on the month it occurs in rather than the following one. Reflects the stored per-deviation value, so it already carries any placement inherited from an adjacent sick period rather than what the submitter originally sent. Not the resolved salary month, which additionally depends on locked-month redirection. |
| `FromDate` | `string(date-time)` | Start date for the salary deviation. |
| `ToDate` | `string(date-time)` | End date for the salary deviation. |
| `Value`? | `number(double)` | Value of the salary deviation. This will be total number of hours or monetary value depending on the type of deviation. |
| `AmountDescriptions`? | [`WintSalary.Deviations.AmountDescription`](#schema-wintsalary-deviations-amountdescription)[] | List of amount with description for the salary deviation. |
| `ChildName`? | `string` | Name of the child for whom the salary deviation is being requested. |
| `ChildId`? | `string(uuid)` | Unique identifier of the child for whom the salary deviation is being requested. Required for parental leave deviations when the EnableChildRecords flag is enabled. |
| `ChildDateOfBirth`? | `string(date-time)` | Date of birth of the referenced child. Populated in responses for display purposes. |
| `Comment`? | `string` | Comment or description for the salary deviation request. |
| `DayMinutes`? | [`WintSalary.Deviations.DayMinutes`](#schema-wintsalary-deviations-dayminutes)[] | List of day and minute entries for the salary deviation request. |
| `TravelCompensation` | [`WintSalary.Deviations.TravelCompensation`](#schema-wintsalary-deviations-travelcompensation) |  |
| `FuelBenefit` | [`WintSalary.Deviations.FuelBenefit`](#schema-wintsalary-deviations-fuelbenefit) |  |

<a id="schema-wintsalary-deviations-salarydeviationcreaterequest"></a>
#### `WintSalary.Deviations.SalaryDeviationCreateRequest`

Represents a request to create a salary deviation.

| Field | Type | Description |
|---|---|---|
| `DeviationTypeId` | `string(uuid)` | Unique identifier for the salary deviation type. |
| `PersonId` | `integer(int32)` | Person Id the salary deviation. |
| `UseCurrentMonthPlacement` | `boolean` | Requests that this deviation be placed on the month it occurs in rather than the following one. Only honoured when the deviation type allows it and the acting user may manage salary; both are enforced by the salary service, so setting it on an ineligible type is rejected rather than ignored. |
| `FromDate` | `string(date-time)` | Start date for the salary deviation. |
| `ToDate` | `string(date-time)` | End date for the salary deviation. |
| `Value`? | `number(double)` | Value of the salary deviation. This will be total number of hours or monetary value depending on the type of deviation. |
| `AmountDescriptions`? | [`WintSalary.Deviations.AmountDescription`](#schema-wintsalary-deviations-amountdescription)[] | List of amount with description for the salary deviation. |
| `ChildName`? | `string` | Name of the child for whom the salary deviation is being requested. |
| `ChildId`? | `string(uuid)` | Unique identifier of the child for whom the salary deviation is being requested. Required for parental leave deviations when the EnableChildRecords flag is enabled. |
| `ChildDateOfBirth`? | `string(date-time)` | Date of birth of the referenced child. Populated in responses for display purposes. |
| `Comment`? | `string` | Comment or description for the salary deviation request. |
| `DayMinutes`? | [`WintSalary.Deviations.DayMinutes`](#schema-wintsalary-deviations-dayminutes)[] | List of day and minute entries for the salary deviation request. |
| `TravelCompensation` | [`WintSalary.Deviations.TravelCompensation`](#schema-wintsalary-deviations-travelcompensation) |  |
| `FuelBenefit` | [`WintSalary.Deviations.FuelBenefit`](#schema-wintsalary-deviations-fuelbenefit) |  |

<a id="schema-wintsalary-deviations-salarydeviationinformationtype"></a>
#### `WintSalary.Deviations.SalaryDeviationInformationType`

Enum: `DateRange`, `DayMinutes`, `DecimalValue`, `Milage`, `TravelCompensationDomestic`, `TravelCompensationInternational`, `FuelBenefit`, `Commission`

<a id="schema-wintsalary-deviations-salarydeviationinformationtypeunit"></a>
#### `WintSalary.Deviations.SalaryDeviationInformationTypeUnit`

Enum: `Amount`, `Hours`, `Kilometer`

<a id="schema-wintsalary-deviations-salarydeviationstate"></a>
#### `WintSalary.Deviations.SalaryDeviationState`

Enum: `Unhandled`, `SoftApproved`, `Approved`, `Rejected`

<a id="schema-wintsalary-deviations-salarydeviationtype"></a>
#### `WintSalary.Deviations.SalaryDeviationType`

Represents a salary deviation type.

| Field | Type | Description |
|---|---|---|
| `Id` | `string(uuid)` | Unique identifier for the salary deviation type. |
| `Name`? | `string` | Name of the salary deviation type. |
| `Category` | [`WintSalary.Deviations.SalaryDeviationTypeCategory`](#schema-wintsalary-deviations-salarydeviationtypecategory) |  |
| `InformationType` | [`WintSalary.Deviations.SalaryDeviationInformationType`](#schema-wintsalary-deviations-salarydeviationinformationtype) |  |
| `InformationTypeUnit` | [`WintSalary.Deviations.SalaryDeviationInformationTypeUnit`](#schema-wintsalary-deviations-salarydeviationinformationtypeunit) |  |
| `LocalizedInformationTypeUnit` | [`LocalizedEnum`](#schema-localizedenum) |  |
| `Hidden` | `boolean` | Indicates whether this salary deviation type is hidden from display. |
| `Classification` | [`WintSalary.Deviations.SalaryDeviationTypeClassification`](#schema-wintsalary-deviations-salarydeviationtypeclassification) |  |
| `CurrentMonthPlacement` | [`WintSalary.Deviations.CurrentMonthPlacement`](#schema-wintsalary-deviations-currentmonthplacement) |  |

<a id="schema-wintsalary-deviations-salarydeviationtypecategory"></a>
#### `WintSalary.Deviations.SalaryDeviationTypeCategory`

Enum: `Absence`, `WorkedHours`, `Compensations`, `TimeBalances`

<a id="schema-wintsalary-deviations-salarydeviationtypeclassification"></a>
#### `WintSalary.Deviations.SalaryDeviationTypeClassification`

Enum: `None`, `SickLeave`, `ParentalLeave`, `TravelCompensation`, `Vab`, `OccupationalInjury`, `Vacation`, `InfectionRisk`, `CareOfCloseRelative`, `UnionEducation`, `TotalDefenceService`, `SfiEducation`, `CompTime`, `SavedSalaryAndVacationPayWithdrawal`, `SavedSalaryWithdrawal`, `SalaryVacationPayWithdrawal`

<a id="schema-wintsalary-deviations-salarydeviationupdaterequest"></a>
#### `WintSalary.Deviations.SalaryDeviationUpdateRequest`

Represents a request to update a salary deviation.

| Field | Type | Description |
|---|---|---|
| `YearMonth`? | `integer(int32)` | Which deviation period(s) to update, by the calendar month (YYYYMM) their dates fall in - not the salary month they are paid in. The new dates must lie within a single selected month, or overlap a selected range. If null, the complete deviation is updated. If set without Wint.Superkoll.API.Model.WintSalary.Deviations.SalaryDeviationUpdateRequest.YearMonthTo, only that single period is updated (e.g. 202502). If set with Wint.Superkoll.API.Model.WintSalary.Deviations.SalaryDeviationUpdateRequest.YearMonthTo, all periods in the inclusive range are updated. |
| `YearMonthTo`? | `integer(int32)` | End of period range for multi-period updates. When both YearMonth and YearMonthTo are set, all periods in the inclusive range are updated. When only YearMonth is set, single-period edit (backward compatible). |
| `FromDate` | `string(date-time)` | Start date for the salary deviation. |
| `ToDate` | `string(date-time)` | End date for the salary deviation. |
| `Value`? | `number(double)` | Value of the salary deviation. This will be total number of hours or monetary value depending on the type of deviation. |
| `AmountDescriptions`? | [`WintSalary.Deviations.AmountDescription`](#schema-wintsalary-deviations-amountdescription)[] | List of amount with description for the salary deviation. |
| `ChildName`? | `string` | Name of the child for whom the salary deviation is being requested. |
| `ChildId`? | `string(uuid)` | Unique identifier of the child for whom the salary deviation is being requested. Required for parental leave deviations when the EnableChildRecords flag is enabled. |
| `ChildDateOfBirth`? | `string(date-time)` | Date of birth of the referenced child. Populated in responses for display purposes. |
| `Comment`? | `string` | Comment or description for the salary deviation request. |
| `DayMinutes`? | [`WintSalary.Deviations.DayMinutes`](#schema-wintsalary-deviations-dayminutes)[] | List of day and minute entries for the salary deviation request. |
| `TravelCompensation` | [`WintSalary.Deviations.TravelCompensation`](#schema-wintsalary-deviations-travelcompensation) |  |
| `FuelBenefit` | [`WintSalary.Deviations.FuelBenefit`](#schema-wintsalary-deviations-fuelbenefit) |  |

<a id="schema-wintsalary-deviations-travelcompensation"></a>
#### `WintSalary.Deviations.TravelCompensation`

Represents travel compensation information for a salary deviation.

| Field | Type | Description |
|---|---|---|
| `CountryCode`? | `string` | Country code (e.g., "SE" for Sweden). |
| `StartTime`? | `string(time)` | Start time of the travel period. |
| `EndTime`? | `string(time)` | End time of the travel period. |
| `Days`? | [`WintSalary.Deviations.TravelCompensationDay`](#schema-wintsalary-deviations-travelcompensationday)[] | List of days with meal payment information. |

<a id="schema-wintsalary-deviations-travelcompensationday"></a>
#### `WintSalary.Deviations.TravelCompensationDay`

Represents a day entry in travel compensation with meal payment information.

| Field | Type | Description |
|---|---|---|
| `Date` | `string(date-time)` | Date for which the meal payment information applies. |
| `BreakfastPaid` | `boolean` | Indicates whether breakfast was paid for this day. |
| `LunchPaid` | `boolean` | Indicates whether lunch was paid for this day. |
| `DinnerPaid` | `boolean` | Indicates whether dinner was paid for this day. |
| `NightlyAllowancePaid` | `boolean` | Whether nightly allowance was paid by the company |

<a id="schema-wintsalary-reapprovalinfo"></a>
#### `WintSalary.ReApprovalInfo`

| Field | Type | Description |
|---|---|---|
| `PersonId` | `integer(int32)` |  |
| `YearMonth` | `integer(int32)` |  |

<a id="schema-wintsalary-salarymonthmutationresultbase"></a>
#### `WintSalary.SalaryMonthMutationResultBase`

| Field | Type | Description |
|---|---|---|
| `ReApprovalInfo` | [`WintSalary.ReApprovalInfo`](#schema-wintsalary-reapprovalinfo) |  |
| `UseCurrentMonthPlacement`? | `boolean` | The placement the salary service actually stored, which is not always the one submitted: a sick deviation continuing an existing period takes that period's placement so one illness pays on one month. Returned so a caller can tell the user its choice was overridden — otherwise the override is indistinguishable from success. Reports the stored flag, not the resolved salary month: locked-month redirection moves a period via `OverrideSalaryYearMonth` without touching this, so an opted-in deviation can still pay on a later month than the flag implies. Only the inheritance override is reportable from here. Set only by the inheritance step, which runs before the merge — the merge predicate requires placement equality, so a merge can never flip it. On a merge the returned id is the surviving pre-existing deviation's, so a caller must not treat it as a newly created row to navigate to. Populated on deviation creates only; null for the other five mutations sharing this base, which is why it is nullable and assigned after construction. Move it to a create-specific result rather than adding a second operation-specific field here — two makes this a bag of nulls. |

<a id="schema-wintsalary-salarymonthmutationresultof-system-guid"></a>
#### `WintSalary.SalaryMonthMutationResultOf_System.Guid`

| Field | Type | Description |
|---|---|---|
| `Result` | `string(uuid)` |  |
| `ReApprovalInfo` | [`WintSalary.ReApprovalInfo`](#schema-wintsalary-reapprovalinfo) |  |
| `UseCurrentMonthPlacement`? | `boolean` | The placement the salary service actually stored, which is not always the one submitted: a sick deviation continuing an existing period takes that period's placement so one illness pays on one month. Returned so a caller can tell the user its choice was overridden — otherwise the override is indistinguishable from success. Reports the stored flag, not the resolved salary month: locked-month redirection moves a period via `OverrideSalaryYearMonth` without touching this, so an opted-in deviation can still pay on a later month than the flag implies. Only the inheritance override is reportable from here. Set only by the inheritance step, which runs before the merge — the merge predicate requires placement equality, so a merge can never flip it. On a merge the returned id is the surviving pre-existing deviation's, so a caller must not treat it as a newly created row to navigate to. Populated on deviation creates only; null for the other five mutations sharing this base, which is why it is nullable and assigned after construction. Move it to a create-specific result rather than adding a second operation-specific field here — two makes this a bag of nulls. |

<a id="schema-wintsalary-scheduleweek"></a>
#### `WintSalary.ScheduleWeek`

A schedule week

| Field | Type | Description |
|---|---|---|
| `Week` | `integer(int32)` | Used to keep track of sort order |
| `Monday` | `integer(int32)` | Expected minutes of work for Monday |
| `Tuesday` | `integer(int32)` | Expected minutes of work for Tuesday |
| `Wednesday` | `integer(int32)` | Expected minutes of work for Wednesday |
| `Thursday` | `integer(int32)` | Expected minutes of work for Thursday |
| `Friday` | `integer(int32)` | Expected minutes of work for Friday |
| `Saturday` | `integer(int32)` | Expected minutes of work for Saturday |
| `Sunday` | `integer(int32)` | Expected minutes of work for Sunday |

<a id="schema-wintsalary-weekbyweekschedule"></a>
#### `WintSalary.WeekByWeekSchedule`

Represents a week by week

| Field | Type | Description |
|---|---|---|
| `ValidFrom` | `string(date)` | Defines from which date the schedule is valid |
| `WorkRate` | `number(double)` | Work rate for the schedule (e.g., 1 for full-time, 0.5 for half-time) |
| `StandardWorkTime` | `integer(int32)` | Standard work time in minutes per week |
| `ScheduleWeeks`? | [`WintSalary.ScheduleWeek`](#schema-wintsalary-scheduleweek)[] | List of schedule weeks defining daily work minutes for each week |

<a id="schema-wintsalary-wintsalarycompanysettings"></a>
#### `WintSalary.WintSalaryCompanySettings`

Represents company-specific settings for salary management functionality.

| Field | Type | Description |
|---|---|---|
| `GrossSalaryChangeEnabled` | `boolean` | Gets or sets a value indicating whether gross salary changes are enabled for the company. |

<a id="schema-wintsalary-wintsalaryoptionallyrequiredfields"></a>
#### `WintSalary.WintSalaryOptionallyRequiredFields`

Enum: `VacationDays`, `VacationCompensation`, `Schedule`, `MonthlyGrossSalary`, `HourlyGrossSalary`

<a id="schema-wintsalary-wintsalaryspecificsettings"></a>
#### `WintSalary.WintSalarySpecificSettings`

Settings specific to Wint Salary system

| Field | Type | Description |
|---|---|---|
| `AvailableSalaryTypes`? | [`WintSalary.WintSalaryType`](#schema-wintsalary-wintsalarytype)[] | Available salary types |
| `SelectedSalaryType` | [`WintSalary.WintSalaryType`](#schema-wintsalary-wintsalarytype) |  |
| `VacationCompensation`? | `number(double)` | Vacation compensation For monthly salaries, this is typically between 0.0043 and 0.01 (0.43-1%). For hourly employed, this is typically between 0.12 and 0.14 (12-14%). |
| `HourlySalary`? | `number(double)` | Hourly gross salary. Null means the employee has no hourly rate. Only present when the salary type uses hourly gross salary in event calculations. |
| `Schedule` | [`WintSalary.WorkSchedule`](#schema-wintsalary-workschedule) |  |
| `TaxPercentage`? | `number(double)` | Percentage tax for the employee. If set it overrides the tax table. |

<a id="schema-wintsalary-wintsalarytype"></a>
#### `WintSalary.WintSalaryType`

Salary type (template group) in WintSalary

| Field | Type | Description |
|---|---|---|
| `Name`? | `string` | Name of salary type |
| `Description`? | `string` | Description of salary type |
| `OptionallyRequiredFields` | [`WintSalary.WintSalaryOptionallyRequiredFields`](#schema-wintsalary-wintsalaryoptionallyrequiredfields) |  |

<a id="schema-wintsalary-workschedule"></a>
#### `WintSalary.WorkSchedule`

Represents a work schedule with validity period, weekly schedules and the first possible date for a schedule change

| Field | Type | Description |
|---|---|---|
| `FirstPossibleScheduleChangeDate`? | `string(date)` | The first date when a schedule change can take effect This will be set to the 1:st of the current month, or the date when the last schedule started if that was later. |
| `CurrentSchedule` | [`WintSalary.WeekByWeekSchedule`](#schema-wintsalary-weekbyweekschedule) |  |
| `FutureSchedule` | [`WintSalary.WeekByWeekSchedule`](#schema-wintsalary-weekbyweekschedule) |  |

<a id="schema-yearandmonth"></a>
#### `YearAndMonth`

| Field | Type | Description |
|---|---|---|
| `Year` | `integer(int32)` |  |
| `Month` | `integer(int32)` |  |

