package io.resttestgen.implementation.fuzzer;

import com.google.common.collect.Sets;
import com.google.gson.Gson;
import io.resttestgen.core.Configuration;
import io.resttestgen.core.Environment;
import io.resttestgen.core.datatype.CRUDSemantics;
import io.resttestgen.core.datatype.NormalizedParameterName;
import io.resttestgen.core.datatype.ParameterName;
import io.resttestgen.core.datatype.parameter.ParameterArray;
import io.resttestgen.core.datatype.parameter.ParameterElement;
import io.resttestgen.core.datatype.parameter.ParameterLeaf;
import io.resttestgen.core.datatype.parameter.ParameterObject;
import io.resttestgen.core.helper.CRUDGroup;
import io.resttestgen.core.openapi.Operation;
import io.resttestgen.core.testing.Fuzzer;
import io.resttestgen.core.testing.TestInteraction;
import io.resttestgen.core.testing.TestRunner;
import io.resttestgen.core.testing.TestSequence;
import io.resttestgen.implementation.parametervalueprovider.multi.KeepLastIdParameterValueProvider;
import io.resttestgen.implementation.parametervalueprovider.multi.RandomProviderParameterValueProvider;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.jetbrains.annotations.NotNull;

import java.io.File;
import java.io.FileWriter;
import java.io.Writer;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Generates mass assignment injection sequences, given a CRUD batch (set of CRUD operations on the same object)
 */
public class MassAssignmentFuzzer extends Fuzzer {

    private static final Logger logger = LogManager.getLogger(MassAssignmentFuzzer.class);
    private static final int MAX_FUZZING_ATTEMPTS = 12;
    private static final int MAX_SEQUENCE_RETRY_ATTEMPTS = 5;
    private static final TestRunner testRunner = TestRunner.getInstance();

    private boolean useInferredCRUDInformation;

    private final Set<Operation> createOperations;
    private final Set<Operation> readOperations;
    private final Set<Operation> updateOperations;
    private final Set<Operation> deleteOperations;

    private final Set<NormalizedParameterName> producerParameterNames;
    private final Set<NormalizedParameterName> consumerParameterNames;
    private final Set<NormalizedParameterName> readOnlyParameterNames;



    private Pattern pattern = Pattern.compile("-?\\d+(\\.\\d+)?");

    public MassAssignmentFuzzer(CRUDGroup crudGroup) {

        this.useInferredCRUDInformation = crudGroup.isInferred();

        this.createOperations = new HashSet<>(crudGroup.getOperations(CRUDSemantics.CREATE));
        this.readOperations = new HashSet<>(crudGroup.getOperations(CRUDSemantics.READ));
        this.readOperations.addAll(crudGroup.getOperations(CRUDSemantics.READ_MULTI));
        this.updateOperations = new HashSet<>(crudGroup.getOperations(CRUDSemantics.UPDATE));
        this.deleteOperations = new HashSet<>(crudGroup.getOperations(CRUDSemantics.DELETE));

        // Compute producer parameters, as the output parameters of 2XX responses of producer operations
        // (read and read-multi operations)
        this.producerParameterNames = new HashSet<>();
        readOperations.forEach(o -> producerParameterNames.addAll(getSuccessfulOutputReferenceLeaves(o).stream().map(ParameterElement::getNormalizedName).collect(Collectors.toSet())));

        // Compute consumer parameters, as the input of consumer operations (create and update operations)
        this.consumerParameterNames = new HashSet<>();
        createOperations.forEach(o -> consumerParameterNames.addAll(o.getAllRequestParameters().stream()
                .map(ParameterElement::getNormalizedName).collect(Collectors.toSet())));
        updateOperations.forEach(o -> consumerParameterNames.addAll(o.getAllRequestParameters().stream()
                .map(ParameterElement::getNormalizedName).collect(Collectors.toSet())));

        // Compute set of read-only parameter normalized names
        readOnlyParameterNames = new HashSet<>(Sets.difference(producerParameterNames, consumerParameterNames));

        try {

            LinkedList<String> operations = new LinkedList<>();
            crudGroup.getOperations().forEach(o -> operations.add(o.toString()));

            // create a map
            Map<String, Object> map = new HashMap<>();
            map.put("resourceType", crudGroup.getResourceType());
            map.put("operations", operations);
            map.put("producerParameters", getStringSetFromNormalizedNameSet(producerParameterNames));
            map.put("consumerParameters", getStringSetFromNormalizedNameSet(consumerParameterNames));
            map.put("readOnlyParameters", getStringSetFromNormalizedNameSet(readOnlyParameterNames));

            Configuration configuration = Environment.getInstance().getConfiguration();

            String path = configuration.getOutputPath() + configuration.getTestingSessionName() + "/CRUDgroups/";

            File file = new File(path);

            file.mkdirs();

            // create a writer
            Writer writer = new FileWriter(path + crudGroup.getResourceType() + ".json");

            // convert map to JSON File
            new Gson().toJson(map, writer);

            // close the writer
            writer.close();

        } catch (Exception ex) {
            ex.printStackTrace();
        }

        //System.out.println("\nRead only parameters: " + readOnlyParameterNames);
    }

    private Set<String> getStringSetFromNormalizedNameSet(Set<NormalizedParameterName> normalizedParameterNames) {
        Set<String> set = new HashSet<>();
        normalizedParameterNames.forEach(n -> set.add(n.toString()));
        return set;
    }

    public List<TestSequence> generateTestSequences() {
        List<TestSequence> testSequences = new LinkedList<>();
        testSequences.addAll(generateUpdateInjectionSequence());
        testSequences.addAll(generateCreateInjectionSequence());
        return testSequences;
    }

    private List<TestSequence> generateCreateInjectionSequence() {

        List<TestSequence> testSequences = new LinkedList<>();

        // If create operations are not available, skip
        if (createOperations.size() == 0) {
            return testSequences;
        }

        // For each read only parameter generate sequence C+ -> R ( -> D -> R )?
        for (NormalizedParameterName readOnlyParameterName : readOnlyParameterNames) {

            // Remove read operations that do not output the read-only parameter
            Set<Operation> readOperationsWithReadOnlyParameters = readOperations.stream().filter(o ->
                    operationHasOutputParameter(o, readOnlyParameterName)).collect(Collectors.toSet());

            for (Operation createOperation : createOperations) {

                // If the create operation does not output a resource identifier, the use only read-multi operations,
                // and execute the read-multi operation before and after creating the resource to determine with a diff
                // what is the identifier of the created resource.
                boolean createOperationDoesNotOutputResourceIdentifier =
                        !operationHasOutputWithResourceIdentifier(createOperation);

                if (createOperationDoesNotOutputResourceIdentifier) {
                    readOperationsWithReadOnlyParameters = readOperationsWithReadOnlyParameters.stream()
                            .filter(this::operationHasOutputWithResourceIdentifier).collect(Collectors.toSet());
                }

                for (Operation readOperation : readOperationsWithReadOnlyParameters) {

                    int remainingSequenceAttempts = MAX_SEQUENCE_RETRY_ATTEMPTS;

                    while (remainingSequenceAttempts > 0) {

                        try {

                            logger.info("Trying CREATE injection on parameter: " + readOnlyParameterName);
                            logger.info("Create operation: " + createOperation);
                            logger.info("Read operation: " + readOperation);

                            TestSequence finalTestSequence = new TestSequence();
                            finalTestSequence.readOnlyParameter = readOnlyParameterName.toString();
                            finalTestSequence.setGenerator(this);
                            finalTestSequence.addTag("create-injection");
                            Optional<Operation> readMultiOperation = Optional.empty();

                            if (createOperationDoesNotOutputResourceIdentifier) {
                                readMultiOperation = Optional.of(readOperation.deepClone());
                                TestSequence readMultiSuccessfulSeq = fuzzUntilSuccessful(readMultiOperation.get(), null);
                                if (readMultiSuccessfulSeq != null) {
                                    finalTestSequence.append(readMultiSuccessfulSeq);
                                } else {
                                    throw new RuntimeException();
                                }
                            }

                            Operation injectedOperation = injectParameter(readOperation, readOnlyParameterName, createOperation);
                            TestSequence injectedSequence = fuzzUntilSuccessful(injectedOperation, null);
                            finalTestSequence.append(injectedSequence);

                            Object resourceIdentifierValue = null;

                            if (createOperationDoesNotOutputResourceIdentifier) {
                                TestInteraction readInteraction =
                                        new TestInteraction(finalTestSequence.get(0).getOperation().deepClone());
                                TestSequence readSequence = new TestSequence(this, readInteraction);
                                testRunner.run(readSequence);
                                finalTestSequence.append(readSequence);
                                resourceIdentifierValue = extractNewlyCreatedResourceIdentifier(finalTestSequence.get(0).getOperation(),
                                        readSequence.get(0).getOperation());
                            } else {
                                resourceIdentifierValue = extractNewlyCreatedResourceIdentifier(injectedSequence.getFirst().getOperation());
                                TestSequence readSequence = fuzzUntilSuccessful(readOperation, resourceIdentifierValue);
                                finalTestSequence.append(readSequence);
                            }

                            TestSequence replayTestSequence = replay(changeInjectedParameters(finalTestSequence),
                                    resourceIdentifierValue);

                            finalTestSequence.append(replayTestSequence);

                            SimpleDateFormat dformat = new SimpleDateFormat("yyyyMMddHHmmssSSS");
                            finalTestSequence.setName("mass_assignment_create-injection_" + dformat.format(finalTestSequence.getGeneratedAt()));

                            testSequences.add(finalTestSequence);

                            // If the sequence could be completed, then exit attempts cycle
                            remainingSequenceAttempts = 0;
                            logger.info("Sequence execution completed.");
                        } catch (RuntimeException e) {
                            remainingSequenceAttempts--;
                            logger.warn("Could not complete sequence execution. Retrying.");
                        }
                    }
                }
            }
        }
        return testSequences;
    }

    private List<TestSequence> generateUpdateInjectionSequence() {

        List<TestSequence> testSequences = new LinkedList<>();

        // If create operations or update operations are not available, skip
        if (createOperations.size() == 0 || updateOperations.size() == 0) {
            return testSequences;
        }

        // For each read only parameter generate sequence C -> R -> U+ -> R ( -> D -> R )?
        for (NormalizedParameterName readOnlyParameterName : readOnlyParameterNames) {

            // Remove read operations that do not output the read-only parameter
            Set<Operation> readOperationsWithReadOnlyParameters = readOperations.stream().filter(o ->
                    operationHasOutputParameter(o, readOnlyParameterName)).collect(Collectors.toSet());

            for (Operation createOperation : createOperations) {

                // If the create operation does not output a resource identifier, the use only read-multi operations,
                // and execute the read-multi operation before and after creating the resource to determine with a diff
                // what is the identifier of the created resource.
                boolean createOperationDoesNotOutputResourceIdentifier =
                        !operationHasOutputWithResourceIdentifier(createOperation);

                if (createOperationDoesNotOutputResourceIdentifier) {
                    readOperationsWithReadOnlyParameters = readOperationsWithReadOnlyParameters.stream()
                            .filter(this::operationHasOutputWithResourceIdentifier).collect(Collectors.toSet());
                }

                for (Operation readOperation : readOperationsWithReadOnlyParameters) {

                    for (Operation updateOperation : updateOperations) {

                        int remainingSequenceAttempts = MAX_SEQUENCE_RETRY_ATTEMPTS;

                        while (remainingSequenceAttempts > 0) {

                            try {

                                logger.info("Trying UPDATE injection on parameter: " + readOnlyParameterName);
                                logger.info("Create operation: " + createOperation);
                                logger.info("Read operation: " + readOperation);
                                logger.info("Update operation: " + updateOperation);

                                TestSequence finalTestSequence = new TestSequence();
                                finalTestSequence.setGenerator(this);
                                finalTestSequence.addTag("update-injection");
                                finalTestSequence.readOnlyParameter = readOnlyParameterName.toString();
                                Optional<Operation> readMultiOperation = Optional.empty();

                                if (createOperationDoesNotOutputResourceIdentifier) {
                                    readMultiOperation = Optional.of(readOperation.deepClone());
                                    TestSequence readMultiSuccessfulSeq = fuzzUntilSuccessful(readMultiOperation.get(), null);
                                    if (readMultiSuccessfulSeq != null) {
                                        finalTestSequence.append(readMultiSuccessfulSeq);
                                    } else {
                                        throw new RuntimeException("Could not fuzz preliminary read-multi operation.");
                                    }
                                }

                                TestSequence createSequence = fuzzUntilSuccessful(createOperation, null);
                                finalTestSequence.append(createSequence);

                                Object resourceIdentifierValue = null;

                                if (createOperationDoesNotOutputResourceIdentifier) {
                                    TestInteraction readInteraction =
                                            new TestInteraction(finalTestSequence.get(0).getOperation().deepClone());
                                    TestSequence readSequence = new TestSequence(this, readInteraction);
                                    testRunner.run(readSequence);
                                    finalTestSequence.append(readSequence);
                                    resourceIdentifierValue = extractNewlyCreatedResourceIdentifier(finalTestSequence.get(0).getOperation(),
                                            readSequence.get(0).getOperation());
                                } else {
                                    resourceIdentifierValue = extractNewlyCreatedResourceIdentifier(createSequence.getFirst().getOperation());
                                    TestSequence readSequence = fuzzUntilSuccessful(readOperation, resourceIdentifierValue);
                                    finalTestSequence.append(readSequence);
                                }

                                Operation injectedOperation = injectParameter(readOperation, readOnlyParameterName, updateOperation);
                                TestSequence injectedSequence = fuzzUntilSuccessful(injectedOperation, resourceIdentifierValue);
                                finalTestSequence.append(injectedSequence);

                                if (createOperationDoesNotOutputResourceIdentifier) {
                                    TestInteraction readInteraction =
                                            new TestInteraction(finalTestSequence.get(0).getOperation().deepClone());
                                    TestSequence readSequence = new TestSequence(this, readInteraction);
                                    testRunner.run(readSequence);
                                    finalTestSequence.append(readSequence);
                                } else {
                                    TestSequence readSequence = fuzzUntilSuccessful(readOperation, resourceIdentifierValue);
                                    finalTestSequence.append(readSequence);
                                }

                                TestSequence replayTestSequence = replay(changeInjectedParameters(finalTestSequence),
                                        resourceIdentifierValue);

                                finalTestSequence.append(replayTestSequence);

                                SimpleDateFormat dformat = new SimpleDateFormat("yyyyMMddHHmmssSSS");
                                finalTestSequence.setName("mass_assignment_update-injection_" + dformat.format(finalTestSequence.getGeneratedAt()));

                                testSequences.add(finalTestSequence);

                                // If the sequence could be completed, then exit attempts cycle
                                remainingSequenceAttempts = 0;
                                logger.info("Sequence execution completed.");
                            } catch (RuntimeException e) {
                                remainingSequenceAttempts--;
                                logger.warn("Could not complete sequence execution. Retrying.");
                            }
                        }
                    }
                }
            }
        }
        return testSequences;
    }




    public boolean isApplicable() {
        return readOnlyParameterNames.size() > 0;
    }

    private TestSequence appendDeleteAndReadOperations(TestSequence testSequence, Operation chosenReadOperation) {
        for (Operation operation : deleteOperations) {
            NominalFuzzer nominalFuzzer = new NominalFuzzer(operation);
            nominalFuzzer.setParameterValueProvider(new KeepLastIdParameterValueProvider());
            nominalFuzzer.generateTestSequences(1);
        }

        // Finally, append a clone of the chosen READ operation
        testSequence.append(new TestInteraction(chosenReadOperation.deepClone()));

        return testSequence;
    }

    /**
     * Verify if an operation contains an output parameter with a given normalized parameter name.
     * @param operation in which searching for parameters.
     * @param normalizedParameterName the normalized name of the parameter to search.
     * @return true if the operation contains a parameter with the given normalized parameter name.
     */
    private boolean operationHasOutputParameter(Operation operation, NormalizedParameterName normalizedParameterName) {
        for (ParameterLeaf leaf : getSuccessfulOutputReferenceLeaves(operation)) {
            if (leaf.getNormalizedName().equals(normalizedParameterName)) {
                return true;
            }
        }
        return false;
    }

    private boolean operationHasOutputWithResourceIdentifier(Operation operation) {
        for (ParameterLeaf leaf : getSuccessfulOutputReferenceLeaves(operation)) {
            if (isCrudResourceIdentifier(leaf)) {
                return true;
            }
        }
        return false;
    }

    private TestSequence fuzzUntilSuccessful(Operation operation, Object identifierValue) throws RuntimeException {
        for (int i = 0; i < MAX_FUZZING_ATTEMPTS; i++) {
            NominalFuzzer nominalFuzzer = new NominalFuzzer(operation.deepClone());
            KeepLastIdParameterValueProvider keepLastIdParameterValueProvider = new KeepLastIdParameterValueProvider();
            keepLastIdParameterValueProvider.setUseInferredCrudSemantics(true);
            keepLastIdParameterValueProvider.setCurrentIdValue(identifierValue);
            nominalFuzzer.setParameterValueProvider(keepLastIdParameterValueProvider);
            TestSequence testSequence = nominalFuzzer.generateTestSequences(1).get(0);
            testRunner.run(testSequence);
            if (testSequence.get(0).getResponseStatusCode().isSuccessful()) {
                return testSequence;
            }
        }
        throw new RuntimeException("Could not fuzz operation " + operation + " successfully.");
    }

    private Operation injectParameter(Operation operationWithParameter, NormalizedParameterName normalizedParameterName,
                                      Operation operationToInject) {

        // The injected operation is the operation to inject, to which the read-only parameter will be added
        Operation injectedOperation = operationToInject.deepClone();

        // Find read-only parameter in read-only operation, siblings are the leaf at the same level
        ParameterLeaf foundLeaf = null;
        Set<NormalizedParameterName> siblings = new HashSet<>();
        for (ParameterLeaf leaf : getSuccessfulOutputReferenceLeaves(operationWithParameter)) {
            if (leaf.getNormalizedName().equals(normalizedParameterName)) {
                foundLeaf = leaf;
                break;
            }
        }
        if (foundLeaf != null && foundLeaf.getParent() != null && foundLeaf.getParent() instanceof ParameterObject) {
            ((ParameterObject) foundLeaf.getParent()).getProperties().forEach(p -> {
                if (!p.getNormalizedName().equals(normalizedParameterName)) {
                    siblings.add(p.getNormalizedName());
                }
            });
        }

        int commonSiblingsCount = 0;
        ParameterObject mostSimilarObject = null;

        // We try to find the more correct location for injection, by maximizing the common siblings
        for (ParameterObject object : injectedOperation.getRequestBody().getReferenceObjects()) {
            List<NormalizedParameterName> objectParameters = object.getProperties().stream()
                    .map(ParameterElement::getNormalizedName).collect(Collectors.toList());

            // Keep only elements which are in common with the siblings
            objectParameters.retainAll(siblings);

            if (objectParameters.size() >= commonSiblingsCount) {
                commonSiblingsCount = objectParameters.size();
                mostSimilarObject = object;
            }
        }

        if (mostSimilarObject != null && foundLeaf != null) {
            ParameterElement injectedLeaf = foundLeaf.deepClone();
            injectedLeaf.addTag("injected");
            injectedLeaf.setParent(mostSimilarObject);
            injectedLeaf.setRequired(true);
            mostSimilarObject.addProperty(injectedLeaf);
        }

        // TODO: Also consider similarity with query parameters

        return injectedOperation;
    }

    /**
     * Changes the value of injected parameters to a new value, different from the previous.
     * @param testSequence the test sequence in which to change injected values.
     * @return and identical (but cloned) test sequence with changed injected parameters values.
     */
    private TestSequence changeInjectedParameters(TestSequence testSequence) {
        TestSequence changedTestSequence = testSequence.deepClone();
        for (TestInteraction interaction : changedTestSequence) {
            for (ParameterLeaf leaf : interaction.getOperation().getLeaves()) {
                if (leaf.getTags().size() > 0 && leaf.getTags().contains("injected")) {
                    if (leaf.getConcreteValue() instanceof Boolean) {
                        leaf.setValue(!((Boolean) leaf.getConcreteValue()));
                    } else if (leaf.isEnum()) {
                        Set<Object> possibleValues = leaf.getEnumValues();
                        possibleValues.remove(leaf.getConcreteValue());
                        Optional<Object> selectedValue =
                                Environment.getInstance().getRandom().nextElement(possibleValues);
                        if (selectedValue.isPresent()) {
                            leaf.setValue(selectedValue.get());
                        } else {
                            logger.warn("Could not change value of enum parameters because only one enum value is " +
                                    "provided and it is already in use.");
                        }
                    } else {
                        RandomProviderParameterValueProvider valueProvider = new RandomProviderParameterValueProvider();
                        Object newValue = valueProvider.provideValueFor(leaf);
                        while (newValue.toString().equals(leaf.getConcreteValue().toString())) {
                            newValue = valueProvider.provideValueFor(leaf);
                        }
                        leaf.setValue(newValue);
                    }
                }
            }
        }
        return changedTestSequence;
    }

    /**
     * Prepares a test sequence to be replayed:
     * - resets the results of previous executions
     * - replaces resource identifiers in create operations to avoid creating a resource with the same identifier
     * - sets sequence name and tag to "replay" or adds "-replay" to existing tag
     * @param testSequence the test sequence to prepare.
     * @return the prepared test sequence
     */
    private TestSequence replay(TestSequence testSequence, Object currentIdValue) {

        TestSequence toReplayTestSequence = testSequence.deepClone();

        // Reset results from previous executions
        toReplayTestSequence.reset();

        // Set name
        if (testSequence.getName() != null) {
            testSequence.setName(testSequence.getName() + "-replay");
        } else {
            testSequence.setName("replay");
        }

        // Set tag
        if (testSequence.getTags().size() > 0) {
            testSequence.addTag(testSequence.getTags().toArray()[0] + "-replay");
        } else {
            testSequence.addTag("replay");
        }

        // Set new value for resource identifiers parameters or unique parameters.
        // Unique parameters' name ends with id or name.
        for (TestInteraction interaction : toReplayTestSequence) {
            if (getCRUDSemantics(interaction.getOperation()).equals(CRUDSemantics.CREATE)) {
                for (ParameterLeaf leaf : interaction.getOperation().getLeaves()) {
                    if (isCrudResourceIdentifier(leaf) || leaf.getNormalizedName().toString().toLowerCase().endsWith("id") ||
                            leaf.getNormalizedName().toString().toLowerCase().endsWith("nam") ||
                            leaf.getNormalizedName().toString().toLowerCase().endsWith("name")) {
                        KeepLastIdParameterValueProvider parameterValueProvider = new KeepLastIdParameterValueProvider();
                        leaf.setValue(parameterValueProvider.provideValueFor(leaf));
                    }
                }
            }
            if (getCRUDSemantics(interaction.getOperation()).equals(CRUDSemantics.UPDATE)) {
                for (ParameterLeaf leaf : interaction.getOperation().getLeaves()) {
                    if (!isCrudResourceIdentifier(leaf)  && (leaf.getNormalizedName().toString().toLowerCase().endsWith("id") ||
                            leaf.getNormalizedName().toString().toLowerCase().endsWith("nam") ||
                            leaf.getNormalizedName().toString().toLowerCase().endsWith("name"))) {
                        KeepLastIdParameterValueProvider parameterValueProvider = new KeepLastIdParameterValueProvider();
                        leaf.setValue(parameterValueProvider.provideValueFor(leaf));
                    }
                }
            }
        }

        int subsequenceSize = 1;
        if (getCRUDSemantics(testSequence.get(0).getOperation()).equals(CRUDSemantics.READ_MULTI)) {
            subsequenceSize = 3;
        }

        testRunner.run(toReplayTestSequence.getSubSequence(0, subsequenceSize));

        Object newIdentifierValue;

        if (subsequenceSize == 1) {
            newIdentifierValue = extractNewlyCreatedResourceIdentifier(toReplayTestSequence.getFirst().getOperation());
        } else {
            newIdentifierValue = extractNewlyCreatedResourceIdentifier(toReplayTestSequence.getFirst().getOperation(),
                    toReplayTestSequence.get(2).getOperation());
        }

        TestSequence secondPart = toReplayTestSequence.getSubSequence(subsequenceSize, toReplayTestSequence.size());

        for (TestInteraction interaction : secondPart) {
            for (ParameterLeaf leaf : interaction.getOperation().getLeaves()) {
                if (isCrudResourceIdentifier(leaf) && leaf.getConcreteValue().toString().equals(currentIdValue.toString())) {
                    leaf.setValue(newIdentifierValue);
                }
            }
        }

        testRunner.run(secondPart);

        return toReplayTestSequence;
    }

    private CRUDSemantics getCRUDSemantics(Operation operation) {
        if (useInferredCRUDInformation) {
            return operation.getInferredCrudSemantics();
        }
        return operation.getCrudSemantics();
    }

    private boolean isCrudResourceIdentifier(ParameterLeaf leaf) {
        if (useInferredCRUDInformation) {
            return leaf.isInferredResourceIdentifier();
        }
        return leaf.isResourceIdentifier();
    }

    public void setUseInferredCRUDInformation(boolean useInferredCRUDInformation) {
        this.useInferredCRUDInformation = useInferredCRUDInformation;
    }

    private Set<String> getSetOfIdentifiers(ParameterArray array, ParameterName identifierName) {

        Set<String> identifiers = new HashSet<>();

        for (ParameterElement element : array.getElements()) {
            for (ParameterLeaf leaf : element.getLeaves()) {
                if (leaf.getName().equals(identifierName)) {
                    identifiers.add(leaf.getConcreteValue().toString());
                }
            }
        }

        return identifiers;
    }

    private ParameterElement getElementWithIdentifierEqualTo(ParameterArray array, ParameterName identifierName, String identifierValue) {
        for (ParameterElement element : array.getElements()) {
            for (ParameterLeaf leaf : element.getLeaves()) {
                if (leaf.getName().equals(identifierName) && leaf.getValue().toString().equals(identifierValue)) {
                    return element;
                }
            }
        }
        return null;
    }

    private ParameterArray getResponseBodyHigherLevelArray(Operation operation) {

        ParameterElement responseBody = operation.getResponseBody();

        if (responseBody != null) {
            if (responseBody instanceof ParameterArray) {
                return (ParameterArray) responseBody;
            } else if (responseBody instanceof ParameterObject) {
                for (ParameterElement element : ((ParameterObject) responseBody).getProperties()) {
                    if (element instanceof ParameterArray) {
                        return (ParameterArray) element;
                    }
                }
            }
        }
        return null;
    }

    private ParameterName getResourceIdentifierName(Operation operation) {
        for (ParameterLeaf leaf : getSuccessfulOutputReferenceLeaves(operation)) {
            if (isCrudResourceIdentifier(leaf)) {
                return leaf.getName();
            }
        }
        return null;
    }



    private ParameterElement extractNewlyCreatedObject(Operation before, Operation after) {

        ParameterName resourceIdentifierName = getResourceIdentifierName(before);
        ParameterArray beforeArray = getResponseBodyHigherLevelArray(before);
        ParameterArray afterArray = getResponseBodyHigherLevelArray(after);

        if (beforeArray != null && afterArray != null && resourceIdentifierName != null &&
                beforeArray.getElements().size() < afterArray.getElements().size() &&
                resourceIdentifierName.equals(getResourceIdentifierName(after))) {

            Set<String> beforeIdentifiers = getSetOfIdentifiers(beforeArray, resourceIdentifierName);
            Set<String> afterIdentifiers = getSetOfIdentifiers(afterArray, resourceIdentifierName);

            Set<String> diff = Sets.difference(afterIdentifiers, beforeIdentifiers);

            if (diff.size() == 1) {
                for (String value : diff) {
                    return getElementWithIdentifierEqualTo(afterArray, resourceIdentifierName, value);
                }

            }

        }

        return null;
    }

    public Object extractNewlyCreatedResourceIdentifier(Operation before, Operation after) {
        ParameterName resourceIdentifierName = getResourceIdentifierName(before);
        ParameterArray beforeArray = getResponseBodyHigherLevelArray(before);
        ParameterArray afterArray = getResponseBodyHigherLevelArray(after);

        if (beforeArray != null && afterArray != null && resourceIdentifierName != null &&
                beforeArray.getElements().size() < afterArray.getElements().size() &&
                resourceIdentifierName.equals(getResourceIdentifierName(after))) {

            Set<String> beforeIdentifiers = getSetOfIdentifiers(beforeArray, resourceIdentifierName);
            Set<String> afterIdentifiers = getSetOfIdentifiers(afterArray, resourceIdentifierName);

            Set<String> diff = Sets.difference(afterIdentifiers, beforeIdentifiers);

            if (diff.size() == 1) {
                for (String value : diff) {
                    if (isNumeric(value)) {
                        double numVal = Double.parseDouble(value);
                        if (numVal % 1 == 0) {
                            return Integer.parseInt(value);
                        } else {
                            return numVal;
                        }
                    }
                    return value;
                }
            }
        }
        return null;
    }

    public boolean isNumeric(String strNum) {
        if (strNum == null) {
            return false;
        }
        return pattern.matcher(strNum).matches();
    }

    public Object extractNewlyCreatedResourceIdentifier(Operation createOperation) {
        ParameterName resourceIdentifierName = getResourceIdentifierName(createOperation);

        if (createOperation.getResponseBody() != null) {
            for (ParameterLeaf leaf : createOperation.getResponseBody().getLeaves()) {
                if (leaf.getName().equals(resourceIdentifierName)) {
                    return leaf.getConcreteValue();
                }
            }
        }

        return null;
    }

    @NotNull
    public Collection<ParameterLeaf> getSuccessfulOutputReferenceLeaves(Operation operation) {
        if (operation.getSuccessfulOutputParameters() != null) {
            return operation.getSuccessfulOutputParameters().getReferenceLeaves();
        }
        return new HashSet<>();
    }
}
