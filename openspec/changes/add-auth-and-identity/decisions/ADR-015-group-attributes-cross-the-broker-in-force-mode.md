# ADR-015: Group Attributes Cross the Broker in Force Mode and Are Declared in the User Profile

## Status

Deferred, 2026-09-04. Not implemented by the OpenSpec change `add-auth-and-identity`, and not accepted by it. This file is the draft that task 12.8 installs into `apps/ascend-agent/docs/architecture/decisions/` with this status intact, taking the next free number at that time.

## Deferral, 2026-09-04

No group identifiers cross the broker in this version. Brokering is optional configuration that decides where a person authenticates, and a brokered person's groups are the Keycloak realm groups an administrator assigned. There is no Attribute Importer for a group claim on the brokered-provider template, and therefore no synchronisation mode to get right and no imported attribute to declare in the user profile.

The change goes further than deferring this record and makes its absence a requirement: no brokered identity provider may carry a mapper that imports a group claim, a role claim, or any other attribute the resolved identity derives authorization from. That is a stronger statement than "not yet configured", and it is what makes the deferral safe rather than merely unfinished.

Everything below is kept because all three findings are primary-source facts about Keycloak that cost real work to establish, and every one of them becomes live again the moment a group attribute is imported. Force mode versus import mode, where the wrong choice freezes a person's permissions at their first login forever and nothing about it looks wrong. The declarative user profile, enabled by default since Keycloak 24, silently dropping an undeclared imported attribute after a default flipped in a minor release. The array importer accepting textual elements only, which is also the fact ADR-014 turns on. And the removal test, which is the only thing that tells force mode from import mode from outside.

What has to happen for this record to become active: a decision to import group identifiers across the broker at all, which is one of the answers to the open question about how a directory's groups relate to Keycloak's, and which the change deliberately does not take.

## Context

ADR-013 puts a broker between the customer's identity provider and ascend-ai-agent. The agent reads a Keycloak token, not the customer's token, so anything the customer's provider asserted reaches the agent only if a mapper deliberately copied it across.

For group identifiers the route is documented and single: an Attribute Importer on the brokered provider copies the array claim element by element into a multivalued user attribute, and a protocol mapper puts that attribute into the access token as an array. Attributes declared this way are administrator-context by default, so the signed-in person cannot write their own group list, which is the property that makes trusting the resulting claim defensible at all.

That route has three configuration points, and each of them has a wrong setting that produces an authorization bug rather than an error. All three were verified against primary sources, and all three fail the same way from the outside: the person authenticates, every request returns 200, and they cannot find documents they can open in SharePoint.

The synchronisation mode is the first. Under force the attribute is refreshed on every login and is actively removed when the claim is absent. Under import it is written once at first login and never updated again. The default is not force. A mapper created by clicking through the console and accepting defaults produces a deployment where everybody's permissions are frozen at the moment they first signed in, and nothing about it looks wrong: the login succeeds, the claim is populated, the principals are well formed, and they are the wrong ones forever.

The user profile declaration is the second. Since Keycloak 24 the declarative user profile is enabled by default, and an attribute that a mapper imports but the user profile does not declare is dropped silently. The importer runs, reports nothing, and the attribute does not exist. That default flipped in a minor release and turned working configurations into silently failing ones.

The claim shape is the third. The array importer accepts only textual elements. An array of strings works. An array of objects is dropped with a warning. This is also the fact ADR-014 turns on, because it is why the Entra overage markers cannot cross the broker.

## Decision

The group route across the broker is fixed, and its three settings are part of the checked-in realm export rather than console state.

1. The Attribute Importer's synchronisation mode is force. Import mode is not used anywhere, for any attribute, on any brokered provider.
2. Every attribute any brokered provider imports is declared in the realm's declarative user profile, administrator-writable and not user-writable.
3. The imported claim is an array of textual elements. A customer whose provider emits group objects has the claim reshaped on their side, and the runbook says so rather than describing a mapper workaround.

Because all three failures are silent, configuration review is not the control. Two things are.

The first is a test that no code review substitutes for: remove a person from a group at the customer's directory, have them sign in again, and assert that the principal disappears from their resolved set and that chunks whose access list names only that group are no longer retrieved for them. It is the only test that distinguishes force mode from import mode from outside, and it is a required task rather than a suggested one.

The second is that an onboarding is closed by a verification sign-in resolving a real tenant and a real principal set, not by a successful login. Every failure in this record produces a successful login.

The realm export carries a disabled brokered-provider template with this mapper set already correct, so creating a customer's provider is copying a reviewed shape rather than assembling one from the console during an onboarding.

## Consequences

### Why this way

- Force mode is the only mode under which a revocation at the customer's directory ever reaches us. Import mode does not degrade the guarantee, it removes it, and it does so in a direction that grants access rather than denying it.
- The user profile declaration living in the export means the failure cannot be introduced by a partial configuration. An attribute added to a provider without being added to the profile is caught by the onboarding verification instead of shipping.
- Administrator-context attributes mean a signed-in person cannot write their own group list. Without that property the whole group-principal design would be self-asserted, which is to say not a control.
- Naming the three failures explicitly, with the shape each one produces, turns a diagnosis that would otherwise start at chunking and embeddings into one that starts at four candidate causes. That is most of the value of writing this down.

### Trade-offs

- Force mode means every login writes attributes, so a person's group set is rewritten on each sign-in rather than only when it changed. That is cheap and it is the correct trade, but it is not free and it makes login slightly more expensive than import mode would.
- Force mode plus the absence of the claim is a removal, which is exactly why an over-cap Entra user ends up with nothing rather than with stale data. That is a correct behaviour producing an unwanted outcome, and ADR-014 is the answer to it rather than a weakening of this record.
- The claim path is only usable by customers whose provider emits a plain array of group identifiers. A customer whose claim shape does not fit has to change it or move to the directory path, and we cannot fix it on our side.
- Keycloak's upgrade cadence is now an authorization concern rather than an operational one. The user profile default that flipped in a minor release is the precedent, and the response is to re-run the onboarding verification after an upgrade, which is a standing cost recorded in ADR-013.

### Alternatives considered

- Accept the default synchronisation mode and refresh attributes some other way. Pro: fewer settings to get right during an onboarding. Con: there is no other way. A brokered provider writes its attributes at login and nothing else refreshes them, so the default mode is not a slower refresh, it is no refresh. Rejected.
- Disable the declarative user profile so undeclared attributes are not dropped. Pro: one fewer place an onboarding can go wrong. Con: it turns off a validation surface for every attribute in the realm in order to avoid writing three declarations, and it fights a default that upstream moved toward deliberately. Rejected.
- Work around an object-shaped group claim with a scripted mapper. Pro: onboards a customer whose claim shape we cannot change. Con: it is per-customer code in the identity layer, which is the thing brokering exists to avoid, and it would be the first of many. Rejected in favour of asking the customer to reshape the claim.
- Rely on configuration review rather than the removal test. Pro: cheaper, and the setting is visible in the export. Con: the export can be correct while a provider created later from the console is not, and the failure is invisible from every surface except the one the test exercises. Rejected.

## Related

- ADR-013, which decides brokering and makes this route the only one group identifiers have
- ADR-014, which depends on the textual-elements constraint recorded here
- `docs/architecture/decisions/ADR-M007-group-principals-membership-at-login.md`
- OpenSpec change `add-auth-and-identity`, decisions D2, D15, D16 and D18, capability `identity-brokering`
